#!/usr/bin/env python
import webapp2
from google.appengine.api import app_identity
from google.appengine.api import mail
from conference import ConferenceApi

# handler for using the cache announcements method in conference.py
class SetAnnouncementHandler(webapp2.RequestHandler):
    def get(self):
        """Set Announcement in Memcache."""
        ConferenceApi._cacheAnnouncement()
        self.response.set_status(204)
        # use _cacheAnnouncement() to set announcement in Memcache

# handlers for setting featured speaker for a conference session(s)
class SetFeaturedSpeakerHandler(webapp2.RequestHandler):
    def post(self):
        """Set featured speaker sessions message in memcache."""
        # use _cacheFeaturedSpeaker to set announcement in Memcache, passing
        # the request objects 'speaker' and 'wsck' (websafeConferenceKey) as args.
        ConferenceApi._cacheFeaturedSpeaker(
            self.request.get('speaker'), self.request.get('wsck'))
        self.response.set_status(204)

# handler and function for sending a confirmation email to creator of conference.
class SendConfirmationEmailHandler(webapp2.RequestHandler):
    def post(self):
        """Send email confirming Conference creation."""
        # using mail python api send mail.
        mail.send_mail(
            'noreply@%s.appspotmail.com' % (
                app_identity.get_application_id()),     # from
            self.request.get('email'),                  # to
            'You created a new Conference!',            # subj
            'Hi, you have created a following '         # body
            'conference:\r\n\r\n%s' % self.request.get(
                'conferenceInfo')
        )


# create a url handler for the announcement handler.
# create a url handler for the email confirmation
# Note: These also need to be updated in app.yaml.
app = webapp2.WSGIApplication([
    ('/crons/set_announcement', SetAnnouncementHandler),
    ('/tasks/get_featured_speaker', SetFeaturedSpeakerHandler),
    ('/tasks/send_confirmation_email', SendConfirmationEmailHandler),
], debug=True)
