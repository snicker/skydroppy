import aiohttp
from datetime import datetime, timedelta
import logging

DEFAULT_BASE_URL = "https://api.skydrop.com/"

class SkydropZone(object):
    def __init__(self, controller, id, name):
        self._controller = controller
        self.id = int(id)
        self.name = name
        self._zone_data = {}
        self._zone_state = {}

    @property
    def enabled(self):
        return self._zone_data.get('on',False)

    @property
    def watering(self):
        return self._zone_state.get('zone_watering',False)

    @property
    def time_remaining(self):
        return self._zone_state.get('time_remaining',0)

    async def start_watering(self):
        return await self._controller.water_zone(self.id)

    async def stop_watering(self):
        return await self._controller.stop_watering()

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

    def get_zone(self, zone_id):
        for zone in self._zones:
            if zone.id == int(zone_id):
                return zone
        return None

    async def water_zone(self, zone_id):
        path = "{}controllers/{}/zones/{}/water.zone".format(
            self._client._base_url, self.id, zone_id)
        res = await self._client._post(path)
        logging.debug("water_zone response: {}".format(res))
        if 'success' in res:
            await self.update_state()
            return True
        return False

    async def stop_watering(self):
        path = "{}controllers/{}/water.stop".format(
            self._client._base_url, self.id)
        res = await self._client._post(path)
        logging.debug("stop_watering response: {}".format(res))
        if 'success' in res:
            await self.update_state()
            return True
        return False
        
    async def update(self):
        await self.update_data()
        await self.update_state()
        
    async def update_data(self):
        path = "{}controllers/{}/all.config".format(
            self._client._base_url, self.id)
        res = await self._client._get(path)
        if 'controller_data' in res:
            self._controller_data = res['controller_data']
        if 'zones_data' in res:
            self._zones_data = res['zones_data']
        for zone_data in self._zones_data:
            zone_id = zone_data.get('zone_num')
            zone_name = zone_data.get('name') or "Zone {}".format(zone_id)
            if zone_id:
                zone = self.get_zone(zone_id)
                if not zone:
                    zone = SkydropZone(self, zone_id, zone_name)
                    self._zones.append(zone)
                zone._zone_data = zone_data
            
    async def update_state(self):
        path = "{}controllers/{}/water.state".format(
            self._client._base_url, self.id)
        res = await self._client._get(path)
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
        path = "{}users/get.controller.ids".format(self._base_url)
        res = await self._get(path)
        if 'controller_ids' in res:
            self._controllers = []
            for cdata in res['controller_ids']:
                id = cdata.get('public_controller_id')
                if not self.get_controller(id):
                    name = cdata.get('name')
                    cont = SkydropController(client=self, id=id, name=name)
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