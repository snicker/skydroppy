import aiohttp
import asyncio
from datetime import datetime, timedelta
import json
import logging
import time

DEFAULT_BASE_URL = "https://api.skydrop.com/"

_LOGGER = logging.getLogger(__name__)

class SkydropZone(object):
    def __init__(self, controller, id):
        self._controller = controller
        self.id = int(id)
        self._zone_data = {}
        self._zone_state = {}

    @property
    def name(self):
        return self._zone_data.get('name') or "Zone {}".format(self.id)

    @property
    def enabled(self):
        return self._zone_data.get('on',False)

    @property
    def duration(self):
        return self._zone_data.get('duration', 0)

    @property
    def watering(self):
        return self._zone_state.get('zone_watering',False)

    @property
    def status(self):
        return self._zone_data.get('status')

    @property
    def plants(self):
        return self._zone_data.get('plant','').split(',')

    @property
    def shade(self):
        return self._zone_data.get('shade')

    @property
    def slope(self):
        return self._zone_data.get('slope')

    @property
    def sprinklers(self):
        return self._zone_data.get('sprinkler','').split(',')

    @property
    def time_remaining(self):
        return self._zone_state.get('time_left',0)

    async def start_watering(self):
        return await self._controller.water_zone(self.id)

    async def stop_watering(self):
        return await self._controller.stop_watering()

    async def enable(self):
        return await self._set_active(True)

    async def disable(self):
        return await self._set_active(False)

    async def set_duration(self, duration):
        return await self._set_configuration({"duration": duration})

    async def _set_active(self, active):
        return await self._set_configuration({"on": active})

    async def _set_configuration(self, config):
        return await self._controller._set_zone_configuration(self.id, config)

    def __repr__(self):
        return '"{}" [{}] ({} Zone {})'.format(self.name, "on: {}m".format(self.time_remaining) if self.watering else "off", self._controller.name, self.id)

    async def update(self):
        await self.controller.update()

class SkydropController(object):
    def __init__(self, client, id, name):
        self._client = client
        self.id = id
        self.name = name
        self._controller_data = {}
        self._zones_data = {}
        self._zone_states = {}
        self._zones = []

    @property
    def enabled(self):
        return self._controller_data.get('on') == True

    @property
    def short_id(self):
        return self.id[:8]
    
    @property
    def zones(self):
        return self._zones

    def __repr__(self):
        return 'Ctrlr "{}" [{}] (id:{})'.format(self.name, "On" if self._controller_data.get('on') else "Off", self.id)

    def get_zone(self, zone_id):
        for zone in self._zones:
            if zone.id == int(zone_id):
                return zone
        return None
    
    async def enable(self):
        return await self._set_configuration({"on": True})
    
    async def disable(self):
        return await self._set_configuration({"on": False})

    async def set_name(self, name):
        return await self._set_configuration({"name": name})

    async def water_zone(self, zone_id):
        path = "{}controllers/{}/zones/{}/water.zone".format(
            self._client._base_url, self.id, zone_id)
        res = await self._client._post(path)
        _LOGGER.debug("water_zone response: {}".format(res))
        if 'success' in res:
            await self.update_state()
            return True
        return False

    async def stop_watering(self):
        path = "{}controllers/{}/water.stop".format(
            self._client._base_url, self.id)
        res = await self._client._post(path)
        _LOGGER.debug("stop_watering response: {}".format(res))
        if 'success' in res:
            await self.update_state()
            return True
        return False

    async def _set_configuration(self, data, timeout = 20):
        path = "{}controllers/{}/controller.config".format(
            self._client._base_url, self.id)
        res = await self._client._put(path, json=data)
        _LOGGER.debug("_set_configuration ({}) response: {}".format(data, res))
        expire = time.time() + timeout
        success = res.get('success')
        while not success and expire > time.time():
            await asyncio.sleep(1)
            await self.update_data()
            success = sum([self._controller_data.get(k) != v for k,v in data.items()]) == 0
        if not success:
            _LOGGER.error('failed to update configuration on controller {} with data {} after {}s'.format(self.id, data, timeout))
        return success

    async def _set_zone_configuration(self, zone_id, data, timeout = 20):
        path = "{}controllers/{}/zone.config/{}".format(
            self._client._base_url, self.id, zone_id)
        res = await self._client._put(path, json=data)
        _LOGGER.debug("_set_zone_configuration ({}) response: {}".format(data, res))
        expire = time.time() + timeout
        success = res.get('success')
        zone = self.get_zone(zone_id)
        while not success and expire > time.time():
            await asyncio.sleep(1)
            await self.update_data()
            success = sum([zone._zone_data.get(k) != v for k,v in data.items()]) == 0
        if not success:
            _LOGGER.error('failed to update zone {} config on controller {} with data {} after {}s'.format(zone_id, self.id, data, timeout))
        return success

    async def update(self):
        await self.update_data()
        await self.update_state()
        
    async def update_data(self):
        path = "{}controllers/{}/all.config".format(
            self._client._base_url, self.id)
        res = await self._client._get(path)
        _LOGGER.debug("update_data response: {}".format(res))
        if 'controller_data' in res:
            self._controller_data = res['controller_data']
            self.name = self._controller_data.get('name')
        if 'zones_data' in res:
            self._zones_data = res['zones_data']
        for zone_data in self._zones_data:
            zone_id = zone_data.get('zone_num')
            if zone_id:
                zone = self.get_zone(zone_id)
                if not zone:
                    zone = SkydropZone(self, zone_id)
                    self._zones.append(zone)
                zone._zone_data = zone_data
            
    async def update_state(self):
        path = "{}controllers/{}/water.state".format(
            self._client._base_url, self.id)
        res = await self._client._get(path)
        _LOGGER.debug("update_state response: {}".format(res))
        if res.get('success') and 'zone_states' in res:
            self._zone_states = res['zone_states']
        for zone_state in self._zone_states:
            zone_id = zone_state.get('zone_id')
            if zone_id:
                zone = self.get_zone(zone_id)
                if zone:
                    zone._zone_state = zone_state
            
        
class SkydropClient(object):
    """
    SkydropClient API client
    :param client_id: Client ID for your Skydrop App
    :type token: str
    :param client_secret: Client secret for your Skydrop App
    :type token: str
    :param session: aiohttp session to use or None
    :type session: object or None
    :param timeout: seconds to wait for before triggering a timeout
    :type timeout: integer
    """
    def __init__(self, client_id, client_secret, session=None,
                 timeout=aiohttp.client.DEFAULT_TIMEOUT):
        """
        Creates a new :class:`SkydropClient` instance.
        """
        self._headers = {'Content-Type': 'application/json'}
        if session is not None:
            self._session = session
        else:
            self._session = aiohttp.ClientSession(timeout=timeout)
        
        self._base_url = DEFAULT_BASE_URL
        self._client_id = client_id
        self._client_secret = client_secret
        self._single_controller = False

        self._tokens = {
            'access': None,
            'refresh': None,
            'expires': round(datetime.now().timestamp())
        }
        
        self._controllers = []
        
    def load_token_data(self, data):
        self.set_access_token(data['access'])
        self.set_refresh_token(data['refresh'])
        self._tokens['expires'] = data['expires']
        
    def set_access_token(self, access_token, expires = 86400):
        self._tokens['access'] = access_token
        self._tokens['expires'] = round(datetime.now().timestamp()) + expires
        self._headers['Authorization'] = "Bearer {}".format(self._tokens['access'])
        
    def set_refresh_token(self, refresh_token):
        self._tokens['refresh'] = refresh_token

    def is_token_expired(self):
        return self._tokens['expires'] <= datetime.now().timestamp()
        
    def get_controller(self, id):
        for c in self._controllers:
            if c.id == id:
                return c
        
    async def update_controllers(self):
        if self._single_controller:
            return await self._update_single_controller()
        else:
            return await self._update_multi_controllers()

    async def _update_multi_controllers(self):
        path = "{}users/get.controller.ids".format(self._base_url)
        try:
            res = await self._get(path)
        except SkydropClient.GatewayTimeout:
            _LOGGER.debug("gateway timeout in _update_multi_controllers," + \
                "assuming single controller")
            self._single_controller = True
            return await self._update_single_controller()
        _LOGGER.debug("_update_multi_controllers response: {}".format(res))
        if 'controller_ids' in res:
            for cdata in res['controller_ids']:
                id = cdata.get('public_controller_id')
                if not self.get_controller(id):
                    name = cdata.get('name')
                    cont = SkydropController(client=self, id=id, name=name)
                    self._controllers.append(cont)
        for cont in self._controllers:
            await cont.update()
        return self._controllers

    async def _update_single_controller(self):
        path = "{}users/default.controller.id".format(self._base_url)
        res = await self._get(path)
        _LOGGER.debug("_update_single_controller response: {}".format(res))
        if 'controller_id' in res:
            id = res.get('controller_id')
            if not self.get_controller(id):
                cont = SkydropController(client=self, id=id, name="None")
                self._controllers.append(cont)
        for cont in self._controllers:
            await cont.update()
        return self._controllers
        
    async def get_access_token(self, access_code):
        path = "{}oauth/token".format(self._base_url)
        data = {
            'grant_type': "authorization_code", 
            'code': access_code, 
            'client_id': self._client_id, 
            'client_secret': self._client_secret
        }
        headers = {'Content-Type': 'application/x-www-form-urlencoded'}
        res = await self._post(path, headers=headers, data = data)
        if 'access_token' in res:
            self.set_access_token(res['access_token'], 
                expires = res.get('expires_in',86400))
        if 'refresh_token' in res:
            self.set_refresh_token(res['refresh_token'])
        return res
        
    async def refresh_access_token(self, refresh_token = None):
        refresh_token = refresh_token or self._tokens['refresh']
        if refresh_token is None:
            raise SkydropClient.ClientError("No refresh token provided")
        path = "{}oauth/token".format(self._base_url)
        data = {
            'grant_type': "refresh_token", 
            'refresh_token': refresh_token, 
            'client_id': self._client_id, 
            'client_secret': self._client_secret
        }
        headers = {'Content-Type': 'application/x-www-form-urlencoded'}
        res = await self._post(path, headers=headers, data = data)
        if 'access_token' in res:
            self.set_access_token(res['access_token'], 
                expires = res.get('expires_in',86400))
        if 'refresh_token' in res:
            self.set_refresh_token(res['refresh_token'])
        return res
        
    @staticmethod
    def handle_error(status, error):
        if status == 400:
            raise SkydropClient.BadRequest(error)
        elif status == 401:
            raise SkydropClient.Unauthorized(error)
        elif status == 403:
            raise SkydropClient.Forbidden(error)
        elif status == 429:
            raise SkydropClient.TooManyRequests(error)
        elif status == 500:
            raise SkydropClient.InternalServerError(error)
        elif status == 504:
            raise SkydropClient.GatewayTimeout(error)
        else:
            raise SkydropClient.ClientError(error)

    async def _get(self, path, **kwargs):
        headers = kwargs.pop('headers',None) or self._headers
        async with self._session.get(
                path, headers=headers, **kwargs) as resp:
            if 200 <= resp.status < 300:
                return await resp.json()
            else:
                self.handle_error(resp.status, await resp.text())

    async def _post(self, path, **kwargs):
        headers = kwargs.pop('headers',None) or self._headers
        async with self._session.post(
                path, headers=headers, **kwargs) as resp:
            if 200 <= resp.status < 300:
                return await resp.json()
            else:
                self.handle_error(resp.status, await resp.text())

    async def _put(self, path, **kwargs):
        headers = kwargs.pop('headers',None) or self._headers
        async with self._session.put(
                path, headers=headers, **kwargs) as resp:
            if 200 <= resp.status < 300:
                return await resp.json()
            else:
                self.handle_error(resp.status, await resp.text())

    class ClientError(Exception):
        """Generic Error."""
        pass

    class GatewayTimeout(ClientError):
        """504 Gateway Timeout."""
        pass

    class Unauthorized(ClientError):
        """Failed Authentication."""
        pass

    class BadRequest(ClientError):
        """Request is malformed."""
        pass

    class Forbidden(ClientError):
        """Access is prohibited."""
        pass

    class TooManyRequests(ClientError):
        """Too many requests for this time period."""
        pass

    class InternalServerError(ClientError):
        """Server Internal Error."""
        pass

    class InvalidData(ClientError):
        """Can't parse response data."""
        pass