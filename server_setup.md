

To run the banhammer service, you'll need an ubuntu service.


# Database
In postgres, create a discordbot database.

You'll need the following tables:

table of ban records
```
CREATE TABLE ban_records (
    id SERIAL PRIMARY KEY,
    user_id BIGINT NOT NULL,
    origin_guild_id BIGINT NOT NULL,
    banner_id BIGINT,
    reason TEXT,
    ban_time TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    UNIQUE (user_id, origin_guild_id)  -- ensures you never double-process the same ban
);
```

autoban settings
```
CREATE TABLE guild_settings (
    guild_id BIGINT PRIMARY KEY,
    autoban_mode TEXT NOT NULL DEFAULT 'off'
);
```

Create a discord bot user in postgres, and place their credentials in the `.env`

```
discord=<hidden>
postgres_user=botuser
postgres_password=<pass>
```


Start the server with pm2. `pm2 start banhammer_alerter.py`