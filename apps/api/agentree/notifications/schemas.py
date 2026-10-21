from pydantic import BaseModel, ConfigDict, Field


class PushConfigOut(BaseModel):
    available: bool  # Web Push is configured on this server
    public_key: str | None  # VAPID application server key for PushManager.subscribe()
    devices: int  # this user's devices with alerts on, for this business


class PushKeysIn(BaseModel):
    model_config = ConfigDict(extra="ignore")  # browsers may add fields

    p256dh: str = Field(min_length=1, max_length=128)
    auth: str = Field(min_length=1, max_length=64)


class PushSubscriptionIn(BaseModel):
    """The browser's PushSubscription.toJSON()."""

    model_config = ConfigDict(extra="ignore")

    endpoint: str = Field(min_length=1, max_length=1024)
    keys: PushKeysIn


class PushUnsubscribeIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    endpoint: str = Field(min_length=1, max_length=1024)


class PushDeviceOut(BaseModel):
    subscribed: bool  # this device gets this business's alerts, for the signed-in user


class PushTestOut(BaseModel):
    sent: int
