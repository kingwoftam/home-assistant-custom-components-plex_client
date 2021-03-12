"""
Monitors plex server for a particular machine_id. Reuses much of the code in the official
plex component for hass

For more details about the hass platform, please refer to the documentation at
https://home-assistant.io/components/sensor.plex/
"""
from datetime import timedelta
import logging
import voluptuous as vol

from homeassistant.components.switch import PLATFORM_SCHEMA
from homeassistant.components.media_player.const import (
    MEDIA_TYPE_TVSHOW, MEDIA_TYPE_VIDEO)
from homeassistant.const import (
    DEVICE_DEFAULT_NAME, STATE_IDLE, STATE_OFF, STATE_PAUSED, STATE_PLAYING,
	CONF_NAME, CONF_USERNAME, CONF_PASSWORD, CONF_HOST, CONF_PORT, CONF_TOKEN)
from homeassistant.helpers.entity import Entity
from homeassistant.util import Throttle
import homeassistant.helpers.config_validation as cv
from homeassistant.loader import bind_hass
from homeassistant.helpers.entity_component import EntityComponent
from homeassistant.helpers.restore_state import RestoreEntity

REQUIREMENTS = ['plexapi==3.0.6']

_LOGGER = logging.getLogger(__name__)

CONF_SERVER = 'server'

DEFAULT_HOST = 'localhost'
DEFAULT_NAME = 'PlexATV'
DEFAULT_PORT = 32400

MIN_TIME_BETWEEN_UPDATES = timedelta(seconds=3)

PLATFORM_SCHEMA = PLATFORM_SCHEMA.extend({
    vol.Optional(CONF_HOST, default=DEFAULT_HOST): cv.string,
    vol.Optional(CONF_NAME, default=DEFAULT_NAME): cv.string,
    vol.Optional(CONF_PASSWORD): cv.string,
    vol.Optional(CONF_TOKEN): cv.string,
    vol.Optional(CONF_PORT, default=DEFAULT_PORT): cv.port,
    vol.Optional(CONF_SERVER): cv.string,
    vol.Optional(CONF_USERNAME): cv.string,
    vol.Optional('machine_id'): cv.string
})

def setup_platform(hass, config, add_devices, discovery_info=None):
    """Set up the Plex sensor."""
    name = config.get(CONF_NAME)
    plex_user = config.get(CONF_USERNAME)
    plex_password = config.get(CONF_PASSWORD)
    plex_server = config.get(CONF_SERVER)
    plex_host = config.get(CONF_HOST)
    plex_port = config.get(CONF_PORT)
    plex_token = config.get(CONF_TOKEN)
    plex_machine_id= config.get('machine_id')
    plex_url = 'http://{}:{}'.format(plex_host, plex_port)
    
    add_devices([PlexClientSensor(
        name, plex_url, plex_user, plex_password, plex_server,
        plex_token, plex_machine_id)], True)

class PlexClientSensor(Entity):
    """Representation of a Plex now playing sensor."""
    
    def __init__(self, name, plex_url, plex_user, plex_password,
                 plex_server, plex_token, plex_machine_id):
        """Initialize the sensor."""
        from plexapi.myplex import MyPlexAccount
        from plexapi.server import PlexServer
        
        self._name = name
        self._media_attrs = {}
        self._plex_machine_id = plex_machine_id
        self._player_state = 'idle'
        self._machineIdentifier = plex_machine_id
        self._device = None
        self._is_player_active = False
        self._is_player_available = False
        self._player = None
        self._make = 'AppleTV'
        self._session = None
        self._session_type = None
        self._session_username = None
        self._state = STATE_IDLE
        self._entity_picture = None
        self._plex_url = plex_url
        self._plex_token = plex_token
        self._media_content_id = None
        self._media_content_rating = None
        self._media_content_type = None
        self._media_duration = None
        self._media_image_url = None
        self._media_title = None
        self._media_ratio = None
        self._media_episode = None
        self._media_season = None
        self._media_series_title = None
        
        if plex_token:
            self._server = PlexServer(plex_url, plex_token)
        elif plex_user and plex_password:
            user = MyPlexAccount(plex_user, plex_password)
            server = plex_server if plex_server else user.resources()[0].name
            self._server = user.resource(server).connect()
        else:
            self._server = PlexServer(plex_url)
       
    @Throttle(MIN_TIME_BETWEEN_UPDATES)
    def update(self):
        """Update method for Plex sensor."""
        # new data refresh
        self._clear_media_details()
        
        devices = self._server.clients()
        for device in devices:
	        if device.machineIdentifier == self._machineIdentifier:
	            self._device = device

        sessions = self._server.sessions()
        for sess in sessions:
            if sess.players[0].machineIdentifier == self._machineIdentifier:
                self._session = sess
                self._is_player_available = True
            else:
                self._is_player_available = False                

        if self._session is not None:
            self._player = self._session.players[0]
            self._player_state = self._player.state
            self._session_username = self._session.usernames[0]
            self._make = self._player.device
            self._media_ratio = self._session.media[0].aspectRatio
            self._media_content_id = self._session.ratingKey
            self._media_content_rating = getattr(
                self._session, 'contentRating', None)
        else:
            self._is_player_available = False
            self._player_state = None
            self._entity_picture = '/local/icon/plex.png'
        
        self._set_player_state()

        if self._is_player_active and self._session is not None:
            self._session_type = self._session.type
            self._media_duration = self._session.duration
            #  title (movie name, tv episode name, music song name)
            self._media_title = self._session.title
            # media type
            self._set_media_type()
            self._set_media_image()
            # calculate duration
            duration_min = self._media_duration / 60000
            hours = int (duration_min / 60)
            mins = duration_min - hours * 60
            length = "%d:%02d" % (hours, mins)
            media_attrs = {}
            media_attrs['type'] = self._session_type
            media_attrs['ratio'] = self._media_ratio
            media_attrs['rating'] = self._media_content_rating
            media_attrs['duration'] = length
            media_attrs['user'] = self._session_username
            self._entity_picture = self._media_image_url
            if self._session_type == 'episode':
                media_attrs['title'] = self._media_series_title + " S" + self._media_season + "E" + self._media_episode + " - " + self._media_title
            else:
                media_attrs['title'] = self._media_title
            self._media_attrs = media_attrs
        else:
            self._session_type = None
            self._media_attrs = {"type": "None", "title": "None", "ratio": "None", "rating": "None", "duration": "None", "user": "None"}

    def _clear_media_details(self):
        self._device = None
        self._session = None
        """Set all Media Items to None."""
        # General
        self._media_content_id = None
        self._media_content_rating = None
        self._media_content_type = None
        self._media_duration = None
        self._media_image_url = None
        self._media_title = None
        self._media_ratio = None
        self._entity_picture = None
        # TV Show
        self._media_episode = None
        self._media_season = None
        self._media_series_title = None

    def _set_player_state(self):
        if self._player_state == 'playing':
            self._is_player_active = True
            self._state = STATE_PLAYING
        elif self._player_state == 'paused':
            self._is_player_active = True
            self._state = STATE_PAUSED
        elif self.device:
            self._is_player_active = False
            self._state = STATE_IDLE
        else:
            self._is_player_active = False
            self._state = STATE_OFF

    def _set_media_image(self):
        thumb_url = self._session.thumbUrl
        if (self.media_content_type is MEDIA_TYPE_TVSHOW):
            thumb_url = self._session.url(self._session.grandparentThumb)
        
        if thumb_url is None:
            thumb_url = self._session.url(self._session.art)
        
        self._media_image_url = thumb_url

    def _set_media_type(self):
        if self._session_type in ['clip', 'episode']:
            self._media_content_type = MEDIA_TYPE_TVSHOW
            
            # season number (00)
            if callable(self._session.season):
                self._media_season = str(
                    (self._session.season()).index).zfill(2)
            elif self._session.parentIndex is not None:
                self._media_season = self._session.parentIndex.zfill(2)
            else:
                self._media_season = None
            # show name
            self._media_series_title = self._session.grandparentTitle
            # episode number (00)
            if self._session.index is not None:
                self._media_episode = str(self._session.index).zfill(2)
        
        elif self._session_type == 'movie':
            self._media_content_type = MEDIA_TYPE_VIDEO
            if self._session.year is not None and \
                    self._media_title is not None:
                self._media_title += ' (' + str(self._session.year) + ')'

    @property
    def name(self):
        """Return the name of the sensor."""
        return self._name
    
    @property
    def state(self):
        """Return the state of the sensor."""
        return self._state
    
    @property
    def device_state_attributes(self):
        """Return the state attributes."""
        return self._media_attrs

    @property
    def entity_picture(self):
        """Return the entity picture of the sensor."""
        return self._entity_picture

    @property
    def unique_id(self):
        """Return the id of this plex client."""
        return self._machineIdentifier

    @property
    def machine_identifier(self):
        """Return the machine identifier of the device."""
        return self._machineIdentifier
    
    @property
    def device(self):
        """Return the device, if any."""
        return self._device
    
    @property
    def session(self):
        """Return the session, if any."""
        return self._session

    @property
    def media_content_id(self):
        """Return the content ID of current playing media."""
        return self._media_content_id
    
    @property
    def media_content_type(self):
        """Return the content type of current playing media."""
        if self._session_type == 'clip':
            return MEDIA_TYPE_TVSHOW
        elif self._session_type == 'episode':
            return MEDIA_TYPE_TVSHOW
        elif self._session_type == 'movie':
            return MEDIA_TYPE_VIDEO
        
        return None
    
    @property
    def media_duration(self):
        """Return the duration of current playing media in seconds."""
        return self._media_duration

    @property
    def media_ratio(self):
        """Return the aspect ratio of current playing media in seconds."""
        return self._media_ratio
    
    @property
    def media_image_url(self):
        """Return the image URL of current playing media."""
        return self._media_image_url
    
    @property
    def media_title(self):
        """Return the title of current playing media."""
        return self._media_title
    
    @property
    def media_season(self):
        """Return the season of current playing media (TV Show only)."""
        return self._media_season
    
    @property
    def media_series_title(self):
        """Return the title of the series of current playing media."""
        return self._media_series_title
    
    @property
    def media_episode(self):
        """Return the episode of current playing media (TV Show only)."""
        return self._media_episode
    
    @property
    def make(self):
        """Return the make of the device (ex. SHIELD Android TV)."""
        return self._make