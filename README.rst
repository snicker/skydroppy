=========
skydroppy
=========

A python library to interface with the Skydrop sprinkler controller API.

---------------------------------------------------
first things first: OAuth your app with your users
---------------------------------------------------

To use this library you must have a developer account to the Skydrop API. You can try emailing api@skydrop.com asking for developer access to your account.

You'll have to navigate the OAuth2 flow per the docs to get a user `code` which can be used to collect the access and refresh token for users: 
`Skydrop API Documentation <https://api.skydrop.com/apps/docs>`_

There are a few helper methods in the client to assist with that 

-------------
example code
-------------

documentation coming later, for now, feel free to explore the code

example code::

    import skydroppy 
    import time

    async def main():
        client = skydroppy.SkydropClient(client_key, client_secret)
        # load tokens for the user from your favorite long term storage
        # should match the structure below.
        tokens = load_tokens() 
        #{
        #    'access': <access token>,
        #    'refresh': <refresh token>>,
        #    'expires': <epoch timestamp for when access token expires>
        #}

        if tokens:
            client.load_token_data(tokens) # little helper method
        else:
            tokens = await client.get_access_token(code)
            save_tokens(client._tokens)

        if client.is_token_expired():
            tokens = await client.refresh_access_token()
            save_tokens(client._tokens)
        
        controllers = await client.update_controllers()
        for controller in controllers:
            print(controller)
            for zone in controller.zones:
                if zone.status == 'wired':
                    print(zone)
        
        front_yard = controllers[0]
        back_yard = controllers[1]
        await front_yard.update() #updates status of all zones and controller status
        await front_yard.get_zone(3).start_watering()
        await back_yard.get_zone(1).start_watering()
        time.sleep(120)
        print(back_yard.get_zone(1).time_remaining)
        await back_yard.stop_watering() # stops all zones
        await front_yard.get_zone(3).stop_watering() # also stops all zones.. API/Skydrop limitation

    asyncio.run(main())


