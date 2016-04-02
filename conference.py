#!/usr/bin/env python

"""
conference.py -- Udacity conference server-side Python App Engine API;
    uses Google Cloud Endpoints

$Id: conference.py,v 1.25 2014/05/24 23:42:19 wesc Exp wesc $

created by wesc on 2014 apr 21

"""

__author__ = 'Benjamindavidfraser@gmail.com (Benjamin Fraser)'

import logging
from datetime import datetime

import endpoints
from protorpc import messages
from protorpc import message_types
from protorpc import remote

from google.appengine.ext import ndb
from google.appengine.api import memcache
from google.appengine.api import taskqueue

# Gather all specified model classes for models.py
from models import Profile
from models import ProfileMiniForm
from models import ProfileForm
from models import TeeShirtSize
from models import Conference
from models import ConferenceForm
from models import ConferenceForms
from models import ConferenceQueryForm
from models import ConferenceQueryForms
from models import Session, SessionForm, SessionForms, SessionQueryForms
from models import BooleanMessage
from models import ConflictException
from models import StringMessage

from settings import WEB_CLIENT_ID
from utils import getUserId


# Default dictionary for conference entities.
DEFAULTS = {
    "city": "Default City",
    "maxAttendees": 0,
    "seatsAvailable": 0,
    "topics": [ "Default", "Topic" ],
}

# Default dictionary for conference sessions.
SESSION_DEFAULTS = {
    "highlights": "Default content",
    "typeOfSession": "lecture"
}

# Operators for query filters.
OPERATORS = {
            'EQ':   '=',
            'GT':   '>',
            'GTEQ': '>=',
            'LT':   '<',
            'LTEQ': '<=',
            'NE':   '!='
            }

# Fields for conference query options.
CONF_FIELDS =    {
            'CITY': 'city',
            'TOPIC': 'topics',
            'MONTH': 'month',
            'MAX_ATTENDEES': 'maxAttendees',
            }

# Fields for session query options.
SESSION_FIELDS = {
    'SPEAKER': 'speaker',
    'DATE': 'date',
    'TYPE': 'typeOfSession',
    'TIME': 'startTime',
}

EMAIL_SCOPE = endpoints.EMAIL_SCOPE
API_EXPLORER_CLIENT_ID = endpoints.API_EXPLORER_CLIENT_ID
MEMCACHE_ANNOUNCEMENTS_KEY = "RECENT_ANNOUNCEMENTS"
ANNOUNCEMENT_TPL = ('Last chance to attend! The following conferences '
                    'are nearly sold out: %s')

# Resource container for conference key request.
# NOTE: Resource containers are required when data is passed to us through
# The url request, or querystring data. It still allows us to pass the 
# Message class, such as ConferenceForm or SessionForm, but just with the 
# additional data. 
CONF_GET_REQUEST = endpoints.ResourceContainer(
    message_types.VoidMessage,
    websafeConferenceKey=messages.StringField(1),
)

# Pass ConferenceForm message class and websafe conf key in url.
CONF_POST_REQUEST = endpoints.ResourceContainer(
    ConferenceForm,
    websafeConferenceKey=messages.StringField(1),
)

# Create a session request that supplies SessionForm and
# websafeConferenceKey as part of the url.
SESSION_CREATE_REQUEST = endpoints.ResourceContainer(
    SessionForm,
    websafeConferenceKey=messages.StringField(1),
)

# Resource containers for session key requests.
SESH_GET_REQUEST =  endpoints.ResourceContainer(
    message_types.VoidMessage,
    websafeSessionKey=messages.StringField(1),
)

SESH_POST_REQUEST =  endpoints.ResourceContainer(
    SessionForm,
    websafeSessionKey=messages.StringField(1),
)


# - - - - - - - - - - - - - - - - - - - - - - - - - - - - - -


@endpoints.api( name='conference',
                version='v1',
                allowed_client_ids=[WEB_CLIENT_ID, API_EXPLORER_CLIENT_ID],
                scopes=[EMAIL_SCOPE])
class ConferenceApi(remote.Service):
    """Conference API v0.1"""

# - - - Profile objects - - - - - - - - - - - - - - - - - - -

    def _copyProfileToForm(self, prof):
        """Copy relevant fields from Profile to ProfileForm."""
        # copy relevant fields from Profile to ProfileForm
        pf = ProfileForm()
        for field in pf.all_fields():
            if hasattr(prof, field.name):
                # convert t-shirt string to Enum; just copy others
                if field.name == 'teeShirtSize':
                    setattr(pf, field.name, getattr(TeeShirtSize, getattr(prof, field.name)))
                else:
                    setattr(pf, field.name, getattr(prof, field.name))
        pf.check_initialized()
        return pf


    def _getProfileFromUser(self):
        """Return user Profile from datastore, creating new one if non-existent."""
        user = endpoints.get_current_user()
        if not user:
            raise endpoints.UnauthorizedException('Authorization required')
            
        # get user id by calling getUserId(user)
        user_id = getUserId(user)
        # create a new key of kind Profile from the id
        p_key = ndb.Key(Profile, user_id)
        # get the entity from datastore by using get() on the key
        profile = p_key.get()
        # if no existing profile, create one.
        if not profile:
            profile = Profile(
                key = p_key,
                displayName = user.nickname(), 
                mainEmail= user.email(),
                teeShirtSize = str(TeeShirtSize.NOT_SPECIFIED),
            )
            profile.put() # save the profile to datastore
        return profile      # return Profile


    def _doProfile(self, save_request=None):
        """Get user Profile and return to user, possibly updating it first."""
        # get user Profile
        prof = self._getProfileFromUser()

        # if saveProfile(), process user-modifyable fields
        if save_request:
            for field in ('displayName', 'teeShirtSize'):
                if hasattr(save_request, field):
                    val = getattr(save_request, field)
                    if val:
                        #if field == 'teeShirtSize':
                        #    setattr(prof, field, str(val).upper())
                        #else:
                        #    setattr(prof, field, val)
                        setattr(prof, field, str(val))
                        prof.put()

        # return ProfileForm
        return self._copyProfileToForm(prof)


    @endpoints.method(message_types.VoidMessage, ProfileForm,
            path='profile', http_method='GET', name='getProfile')
    def getProfile(self, request):
        """Return user profile."""
        return self._doProfile()


    @endpoints.method(ProfileMiniForm, ProfileForm,
            path='profile', http_method='POST', name='saveProfile')
    def saveProfile(self, request):
        """Update & return user profile."""
        return self._doProfile(request)


# - - - Conference objects - - - - - - - - - - - - - - - - -

    def _copyConferenceToForm(self, conf, displayName):
        """Copy relevant fields from Conference to ConferenceForm."""
        cf = ConferenceForm()
        for field in cf.all_fields():
            if hasattr(conf, field.name):
                # convert Date to date string; just copy others
                if field.name.endswith('Date'):
                    setattr(cf, field.name, str(getattr(conf, field.name)))
                else:
                    setattr(cf, field.name, getattr(conf, field.name))
            elif field.name == "websafeKey":
                setattr(cf, field.name, conf.key.urlsafe())
        if displayName:
            setattr(cf, 'organizerDisplayName', displayName)
        cf.check_initialized()
        return cf


    def _createConferenceObject(self, request):
        """Create or update Conference object, returning ConferenceForm/request."""
        # preload necessary data items
        user = endpoints.get_current_user()
        if not user:
            raise endpoints.UnauthorizedException('Authorization required')
        user_id = getUserId(user)

        if not request.name:
            raise endpoints.BadRequestException("Conference 'name' field required")

        # copy ConferenceForm/ProtoRPC Message into dict
        data = {field.name: getattr(request, field.name) for field in request.all_fields()}
        del data['websafeKey']
        del data['organizerDisplayName']

        # add default values for those missing (both data model & outbound Message)
        for df in DEFAULTS:
            if data[df] in (None, []):
                data[df] = DEFAULTS[df]
                setattr(request, df, DEFAULTS[df])

        # convert dates from strings to Date objects; set month based on start_date
        if data['startDate']:
            data['startDate'] = datetime.strptime(data['startDate'][:10], "%Y-%m-%d").date()
            data['month'] = data['startDate'].month
        else:
            data['month'] = 0
        if data['endDate']:
            data['endDate'] = datetime.strptime(data['endDate'][:10], "%Y-%m-%d").date()

        # set seatsAvailable to be same as maxAttendees on creation
        # both for data model & outbound Message
        if data["maxAttendees"] > 0:
            data["seatsAvailable"] = data["maxAttendees"]
            setattr(request, "seatsAvailable", data["maxAttendees"])

        # make Profile Key from user ID
        p_key = ndb.Key(Profile, user_id)
        # allocate new Conference ID with Profile key as parent
        c_id = Conference.allocate_ids(size=1, parent=p_key)[0]
        # make Conference key from ID
        c_key = ndb.Key(Conference, c_id, parent=p_key)
        data['key'] = c_key
        data['organizerUserId'] = request.organizerUserId = user_id

        # create Conference & return (modified) ConferenceForm
        # send email confirmation to originator for conference.
        Conference(**data).put()
        # Create a default task queue to send an email confirmation.
        taskqueue.add(params={'email': user.email(),
            'conferenceInfo': repr(request)},
            url='/tasks/send_confirmation_email'
        )

        return request

    # Provide a transaction for updating a conference.
    @ndb.transactional()
    def _updateConferenceObject(self, request):
        user = endpoints.get_current_user()
        if not user:
            raise endpoints.UnauthorizedException('Authorization required')
        user_id = getUserId(user)

        # copy ConferenceForm/ProtoRPC Message into dict
        data = {field.name: getattr(request, field.name) for field in request.all_fields()}

        # update existing conference
        conf = ndb.Key(urlsafe=request.websafeConferenceKey).get()
        # check that conference exists
        if not conf:
            raise endpoints.NotFoundException(
                'No conference found with key: %s' % request.websafeConferenceKey)

        # check that user is owner
        if user_id != conf.organizerUserId:
            raise endpoints.ForbiddenException(
                'Only the owner can update the conference.')

        # Not getting all the fields, so don't create a new object; just
        # copy relevant fields from ConferenceForm to Conference object
        for field in request.all_fields():
            data = getattr(request, field.name)
            # only copy fields where we get data
            if data not in (None, []):
                # special handling for dates (convert string to Date)
                if field.name in ('startDate', 'endDate'):
                    data = datetime.strptime(data, "%Y-%m-%d").date()
                    if field.name == 'startDate':
                        conf.month = data.month
                # write to Conference object
                setattr(conf, field.name, data)
        conf.put()
        prof = ndb.Key(Profile, user_id).get()
        return self._copyConferenceToForm(conf, getattr(prof, 'displayName'))

    # Create a new conference endpoint definition.
    @endpoints.method(ConferenceForm, ConferenceForm, path='conference',
            http_method='POST', name='createConference')
    def createConference(self, request):
        """Create new conference."""
        return self._createConferenceObject(request)

    # Conference queries endpoint definition.
    @endpoints.method(ConferenceQueryForms, ConferenceForms,
                path='queryConferences',
                http_method='POST',
                name='queryConferences')
    def queryConferences(self, request):
        """Query for conferences."""
        conferences = self._getQuery(request)

         # return individual ConferenceForm object per Conference
        return ConferenceForms(
            items=[self._copyConferenceToForm(conf, "") \
            for conf in conferences]
        )

    # Endpoint for updating the conference selected.
    @endpoints.method(CONF_POST_REQUEST, ConferenceForm,
            path='conference/{websafeConferenceKey}',
            http_method='PUT', name='updateConference')
    def updateConference(self, request):
        """Update conference w/provided fields & return w/updated info."""
        return self._updateConferenceObject(request)


    # Return conference requested by websafeConferenceKey
    @endpoints.method(CONF_GET_REQUEST, ConferenceForm,
            path='conference/{websafeConferenceKey}',
            http_method='GET', name='getConference')
    def getConference(self, request):
        """Return requested conference (by websafeConferenceKey)."""
        # get Conference object from request; bail if not found
        conf = ndb.Key(urlsafe=request.websafeConferenceKey).get()
        if not conf:
            raise endpoints.NotFoundException(
                'No conference found with key: %s' % request.websafeConferenceKey)
        prof = conf.key.parent().get()
        # return ConferenceForm
        return self._copyConferenceToForm(conf, getattr(prof, 'displayName'))

    # Get conference created by the user endpoint definition.
    @endpoints.method(message_types.VoidMessage, ConferenceForms,
        path='getConferencesCreated',
        http_method='POST', name='getConferencesCreated')
    def getConferencesCreated(self, request):
        """Return conferences created by user."""
        # make sure user is authed
        user = endpoints.get_current_user()
        if not user:
            raise endpoints.UnauthorizedException('Authorization required')
        user_id = getUserId(user)

        # create ancestor query for all key matches for this user
        confs = Conference.query(ancestor=ndb.Key(Profile, user_id))
        prof = ndb.Key(Profile, user_id).get()
        # return set of ConferenceForm objects per Conference
        return ConferenceForms(
            items=[self._copyConferenceToForm(conf, getattr(prof, 'displayName')) for conf in confs]
        )

    @endpoints.method(message_types.VoidMessage, ConferenceForms,
            path='queryPlayground', http_method='GET', name='queryPlayground')
    def queryPlayground(self, request):
        """Return query search entered."""
        # Return a random search for conferences in London.
        q = Conference.query()
        field = "city"
        operator = "="
        value = "London"
        f = ndb.query.FilterNode(field, operator, value)
        q = q.filter(f)
        return ConferenceForms(
            items=[self._copyConferenceToForm(conf, "") \
            for conf in q]
        )

    @endpoints.method(message_types.VoidMessage, ConferenceForms,
            path='queryPlaygroundExtra', http_method='GET', name='queryPlaygroundExtra')
    def queryPlaygrondExtra(self, request):
        """Return query search entered."""
        # Start by querying all conferences.
        q = Conference.query()
        # Filter this initial query through using .filter() method.
        q = q.filter(Conference.topics == "Medical Innovations")
        # Add yet another filter query to further limit the search.
        q = q.filter(Conference.city == "London")
        # sort the conferences in order of name.
        q = q.order(Conference.name)
        # add in a filter selecting conferences during July only.
        q = q.filter(Conference.maxAttendees > 15)
        # Return the queried conferences as a ConferenceForm object.
        return ConferenceForms(
            items=[self._copyConferenceToForm(conf, "") \
            for conf in q]
        )

    def _getQuery(self, request):
        """Return formatted query from the submitted filters."""
        q = Conference.query()
        # obtain parsed and formatted user query filters from _formatFilters
        inequality_filter, filters = self._formatFilters(request.filters)

        # Sort inequality filter first if it exists from _formatFilters.
        if not inequality_filter:
            q = q.order(Conference.name)
        else:
            q = q.order(ndb.GenericProperty(inequality_filter))
            q = q.order(Conference.name)

        for filtr in filters:
            if filtr["field"] in ["month", "maxAttendees"]:
                filtr["value"] = int(filtr["value"])
            # create a filterNode object containing the custom query, and return it.
            formatted_query = ndb.query.FilterNode(filtr["field"], filtr["operator"], filtr["value"])
            q = q.filter(formatted_query)
        return q

    def _formatFilters(self, filters, queryType='conference'):
        """Parse, check validity and format user supplied filters."""
        formatted_filters = []
        inequality_field = None

        for f in filters:
            filtr = {field.name: getattr(f, field.name) for field in f.all_fields()}

            try:
                if queryType == 'conference':
                    filtr["field"] = CONF_FIELDS[filtr["field"]]
                elif queryType == 'conf_session':
                    filtr["field"] = SESSION_FIELDS[filtr["field"]]
                filtr["operator"] = OPERATORS[filtr["operator"]]
            except KeyError:
                raise endpoints.BadRequestException("Filter contains invalid field or operator.")

            # Every operation except "=" is an inequality
            if filtr["operator"] != "=":
                # check if inequality operation has been used in previous filters
                # disallow the filter if inequality was performed on a different field before
                # track the field on which the inequality operation is performed
                if inequality_field and inequality_field != filtr["field"]:
                    raise endpoints.BadRequestException("Inequality filter is allowed on only one field.")
                else:
                    inequality_field = filtr["field"]

            formatted_filters.append(filtr)
        return (inequality_field, formatted_filters)

# - - - Session objects - - - - - - - - - - - - - - - - -

    def _copySessionToForm(self, theSession, displayName):
        """Copy relevant fields from Session to SessionForm."""
        # create an instance of SessionForm
        sesh = SessionForm()
        for field in sesh.all_fields():
            # to get/set properties with names defined in strings use getattr/setattr.
            if hasattr(theSession, field.name):
                # convert Date to date string; just copy others
                if field.name.endswith('Date'):
                    setattr(sesh, field.name, str(getattr(theSession, field.name)))
                else:
                    setattr(sesh, field.name, getattr(theSession, field.name))
            elif field.name == "websafeKey":
                setattr(sesh, field.name, theSession.key.urlsafe())
        if displayName:
            setattr(sesh, 'creatorDisplayName', displayName)
        sesh.check_initialized()
        return sesh

    def _copySessionToFormAfterCreation(self, data, theSession):
        """Copy data fields from Session object creation to SessionForm."""

        extracted_session = theSession.get()
        logging.info(extracted_session)
        urlsafe_session_key = extracted_session.key.urlsafe()
        data['websafeKey'] = urlsafe_session_key

        prof = ndb.Key(Profile, data['creatorUserId']).get()
        data['creatorDisplayName'] = prof.displayName

        # create an instance of SessionForm
        sesh = SessionForm(
            name="",
            highlights="",
            speaker="",
            date="",
            duration=60,
            startTime="",
            typeOfSession="",
            creatorUserId="",
            websafeKey="",
            creatorDisplayName="")
        sesh.check_initialized()

        # Pass all fields from data into the instance of SessionForm and return.
        for field in sesh.all_fields():
            if data[field.name] and data[field.name] != 'websafeKey':
                if field.name == 'date':
                    setattr(sesh, field.name, str(data[field.name]))
                elif field.name == 'duration':
                    setattr(sesh, field.name, str(data[field.name]))
                else:
                    setattr(sesh, field.name, data[field.name])
            elif field.name == 'websafeKey':
                setattr(sesh, field.name, str(session_object_key))
        sesh.check_initialized()

        return sesh


    def _createSessionObject(self, request):
        """Create or update Session object, returning SessionForm/request."""
        # preload necessary data items
        user = endpoints.get_current_user()
        if not user:
            raise endpoints.UnauthorizedException('Authorization required')
        user_id = getUserId(user)

        # Check for session name in request object - if not raise exception.
        if not request.name:
            raise endpoints.BadRequestException("Session 'name' field required")

        # Check for websafeConferenceKey in request - if not, raise exception.
        if not request.websafeConferenceKey:
            raise endpoints.BadRequestException("Session 'websafeConferenceKey' field required")

        # create a conference key from the given websafeConferenceKey request object.
        conf_key = ndb.Key(urlsafe=request.websafeConferenceKey)

        # fetch conference entity from datastore.
        conf = conf_key.get()

        # Check for conference with corresponding websafeConferenceKey - if not raise excep.
        if not conf:
            raise endpoints.NotFoundException(
                'No conference found with key: %s' % request.websafeConferenceKey)

        # copy SessionForm/ProtoRPC Message into dict
        data = {field.name: getattr(request, field.name) for field in request.all_fields()}
        del data['websafeKey']
        del data['websafeConferenceKey']
        del data['creatorDisplayName']

        # add default values for those missing (both data model & outbound Message)
        for df in SESSION_DEFAULTS:
            if data[df] in (None, []):
                data[df] = SESSION_DEFAULTS[df]
                setattr(request, df, SESSION_DEFAULTS[df])

        # convert dates from strings to Date objects; set month based on start_date
        if data['date']:
            data['date'] = datetime.strptime(data['date'][:10], "%Y-%m-%d").date()

        # allocate new Session ID with Conference key as parent
        s_id = Session.allocate_ids(size=1, parent=conf_key)[0]
        # make Session key from ID
        s_key = ndb.Key(Session, s_id, parent=conf_key)
        data['key'] = s_key
        # make Profile Key from user ID for creatorUserId field in session
        p_key = ndb.Key(Profile, user_id)
        data['creatorUserId'] = request.creatorUserId = user_id

        # create Session & return (modified) SessionForm
        theSession = Session(**data).put()

        # create a SessionForm object and return.
        session_object = self._copySessionToFormAfterCreation(data, theSession)

        return session_object


    # Provide a transaction for updating a session.
    @ndb.transactional()
    def _updateSessionObject(self, request):
        user = endpoints.get_current_user()
        if not user:
            raise endpoints.UnauthorizedException('Authorization required')
        user_id = getUserId(user)

        # copy SessionForm/ProtoRPC Message into dict
        data = {field.name: getattr(request, field.name) for field in request.all_fields()}

        # update existing session
        sesh = ndb.Key(urlsafe=request.websafeSessionKey).get()
        # check that session exists
        if not sesh:
            raise endpoints.NotFoundException(
                'No session found with key: %s' % request.websafeSessionKey)

        # check that user is owner
        if user_id != sesh.creatorUserId:
            raise endpoints.ForbiddenException(
                'Only the owner can update the session.')

        # Not getting all the fields, so don't create a new object; just
        # copy relevant fields from SessionForm to Session object
        for field in request.all_fields():
            data = getattr(request, field.name)
            # only copy fields where we get data
            if data not in (None, []):
                # special handling for dates (convert string to Date)
                if field.name in ('date'):
                    data = datetime.strptime(data, "%Y-%m-%d").date()
                # write to Session object
                setattr(sesh, field.name, data)
        sesh.put()
        prof = ndb.Key(Profile, user_id).get()
        return self._copySessionToForm(sesh, getattr(prof, 'displayName'))


    # Create a new Session endpoint definition.
    @endpoints.method(SESSION_CREATE_REQUEST, SessionForm,
            path='conference/{websafeConferenceKey}/session/create',
            http_method='POST', name='createSession')
    def createSession(self, request):
        """Create new session."""
        return self._createSessionObject(request)


    def _getSessionQuery(self, request):
        """Return formatted query from the submitted filters."""
        q = Session.query()
        # obtain parsed and formatted user query filters from _formatFilters
        inequality_filter, filters = self._formatFilters(request.filters, queryType='conf_sessions')

        # Sort inequality filter first if it exists from _formatFilters.
        if not inequality_filter:
            q = q.order(Session.name)
        else:
            q = q.order(ndb.GenericProperty(inequality_filter))
            q = q.order(Session.name)

        for filtr in filters:
            if filtr["field"] in ["month", "maxAttendees"]:
                filtr["value"] = int(filtr["value"])
            # create a filterNode object containing the custom query, and return it.
            formatted_query = ndb.query.FilterNode(filtr["field"], filtr["operator"], filtr["value"])
            q = q.filter(formatted_query)
        return q


    # Session queries endpoint definition.
    @endpoints.method(SessionQueryForms, SessionForms,
                path='querySessions',
                http_method='POST',
                name='querySessions')
    def querySessions(self, request):
        """Query for sessions."""
        sessions = self._getSessionQuery(request)

         # return individual SessionForm object per Conference
        return SessionForms(
            items=[self._copySessionToForm(sesh, "") \
            for sesh in sessions]
        )

    # Get session created by the user endpoint definition.
    @endpoints.method(message_types.VoidMessage, SessionForms,
        path='getSessionsCreated',
        http_method='POST', name='getSessionsCreated')
    def getSessionsCreated(self, request):
        """Return sessions created by user."""
        # make sure user is authed
        user = endpoints.get_current_user()
        if not user:
            raise endpoints.UnauthorizedException('Authorization required')
        user_id = getUserId(user)
        # create a datastore query for sessions created by user id.
        q = Session.query()
        # Filter this initial query through using .filter() method.
        q = q.filter(Session.creatorUserId == user_id)
        # Return the queried sessions as a SessionForm object.
        return SessionForms(
            items=[self._copySessionToForm(sesh, "") \
            for sesh in q]
        )


    # Endpoint for updating the conference selected.
    @endpoints.method(SESH_POST_REQUEST, SessionForm,
            path='session/{websafeSessionKey}/update',
            http_method='PUT', name='updateSession')
    def updateSession(self, request):
        """Update session w/provided fields & return w/updated info."""
        return self._updateSessionObject(request)


    # Return session requested by websafeSessionKey
    @endpoints.method(SESH_GET_REQUEST, SessionForm,
            path='session/{websafeSessionKey}',
            http_method='GET', name='getSession')
    def getSession(self, request):
        """Return requested session (by websafeSessionKey)."""
        # get Session object from request; bail if not found
        sesh = ndb.Key(urlsafe=request.websafeSessionKey).get()
        if not sesh:
            raise endpoints.NotFoundException(
                'No session found with key: %s' % request.websafeSessionKey)
        # fetch the creators display name using the session creator id.
        prof = ndb.Key(Profile, sesh.creatorUserId).get()
        creator_name = prof.displayName
        # return SessionForm
        return self._copySessionToForm(sesh, creator_name)

    # Return sessions for the selected conference by websafeConferenceKey
    @endpoints.method(CONF_GET_REQUEST, SessionForms,
            path='conference/{websafeConferenceKey}/sessions',
            http_method='GET', name='conferenceSessions')
    def getConferenceSessions(self, request):
        """ Return the requested conference's sessions. """
        # get Conference object from request; bail if not found
        conf = ndb.Key(urlsafe=request.websafeConferenceKey).get()
        if not conf:
            raise endpoints.NotFoundException(
                'No conference found with key: %s' % request.websafeConferenceKey)
        # query all sessions within the conference entity.
        conf_sessions = Session.query(ancestor=ndb.Key(Conference, conf.id))
        # Return the queried sessions as a SessionForm object.
        return SessionForms(
            items=[self._copySessionToForm(sesh, "") \
            for sesh in conf_sessions]
        )

# - - - Registration - - - - - - - - - - - - - - - - - - - -
    
    @ndb.transactional(xg=True)
    def _conferenceRegistration(self, request, reg=True):
        """Register or unregister user for selected conference."""
        retval = None
        prof = self._getProfileFromUser() # get user Profile

        # check if conf exists given websafeConfKey
        # get conference; check that it exists
        wsck = request.websafeConferenceKey
        conf = ndb.Key(urlsafe=wsck).get()
        if not conf:
            raise endpoints.NotFoundException(
                'No conference found with key: %s' % wsck)

        # register
        if reg:
            # check if user already registered otherwise add
            if wsck in prof.conferenceKeysToAttend:
                raise ConflictException(
                    "You have already registered for this conference")

            # check if seats avail
            if conf.seatsAvailable <= 0:
                raise ConflictException(
                    "There are no seats available.")

            # register user, take away one seat
            prof.conferenceKeysToAttend.append(wsck)
            conf.seatsAvailable -= 1
            retval = True

        # unregister
        else:
            # check if user already registered
            if wsck in prof.conferenceKeysToAttend:

                # unregister user, add back one seat
                prof.conferenceKeysToAttend.remove(wsck)
                conf.seatsAvailable += 1
                retval = True
            else:
                retval = False

        # write things back to the datastore & return
        prof.put()
        conf.put()
        return BooleanMessage(data=retval)


    @endpoints.method(CONF_GET_REQUEST, BooleanMessage,
            path='conference/{websafeConferenceKey}',
            http_method='POST', name='registerForConference')
    def registerForConference(self, request):
        """Register user for selected conference."""
        return self._conferenceRegistration(request)

    @endpoints.method(CONF_GET_REQUEST, BooleanMessage,
            path='conference/{websafeConferenceKey}',
            http_method='DELETE', name='unregisterForConference')
    def unregisterForConference(self, request):
        """unregister for the selected conference."""
        return self._conferenceRegistration(request, reg=False)

    @endpoints.method(message_types.VoidMessage, ConferenceForms,
            path='conferences/attending',
            http_method='GET', name='getConferencesToAttend')
    def getConferencesToAttend(self, request):
        """Get list of conferences that user has registered for."""
        # TODO:
        # step 1: get user profile
        prof = self._getProfileFromUser() # get user Profile
        # step 2: get conferenceKeysToAttend from profile.
        conferencesToAttendKeys = [ndb.Key(urlsafe=wsck) for wsck in prof.conferenceKeysToAttend]
        # Make each key within conferencesToAttendKeys urlsafe.
        # to make a ndb key from websafe key you can use:
        # ndb.Key(urlsafe=my_websafe_key_string)
        # step 3: fetch conferences from datastore.
        conferences = ndb.get_multi(conferencesToAttendKeys) 
        # Use get_multi(array_of_keys) to fetch all keys at once.
        # Do not fetch them one by one!

        # return set of ConferenceForm objects per Conference
        return ConferenceForms(items=[self._copyConferenceToForm(conf, "")\
         for conf in conferences]
        )

# - - - Announcements - - - - - - - - - - - - - - - - - - - -

    # Query for conferences that we want to assign to memcache and create announcement.
    # We dont want to expose this as a endpoint, so we give it a private method.
    @staticmethod
    def _cacheAnnouncement():
        """Create Announcement & assign to memcache; used by
        memcache cron job & putAnnouncement().
        """
        # query for conferences that are almost full to announce.
        confs = Conference.query(ndb.AND(
            Conference.seatsAvailable <= 5,
            Conference.seatsAvailable > 0)
        ).fetch(projection=[Conference.name])

        if confs:
            # If there are almost sold out conferences,
            # format announcement and set it in memcache
            logging.debug("Found %s conferences" % len(confs))
            announcement = ANNOUNCEMENT_TPL % (
                ', '.join(conf.name for conf in confs))
            memcache.set(MEMCACHE_ANNOUNCEMENTS_KEY, announcement)
        else:
            # If there are no sold out conferences,
            # delete the memcache announcements entry
            announcement = ""
            logging.debug("The announcement key has been deleted. %s" % MEMCACHE_ANNOUNCEMENTS_KEY)
            print ""
            memcache.delete(MEMCACHE_ANNOUNCEMENTS_KEY)

        return announcement

    # Endpoint for returning memcache announcement to user.
    @endpoints.method(message_types.VoidMessage, StringMessage,
            path='conference/announcement/get',
            http_method='GET', name='getAnnouncement')
    def getAnnouncement(self, request):
        """Return Announcement from memcache."""
        # Return announcement using StringMessage.
        announcement = memcache.get(MEMCACHE_ANNOUNCEMENTS_KEY)
        logging.debug("The announcement key contains: {0}".format(announcement))
        return StringMessage(data=announcement or "")

# registers API
api = endpoints.api_server([ConferenceApi]) 
