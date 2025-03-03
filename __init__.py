# The MIT License (MIT)
#
# Copyright (c) 2018 Michael P. Scherer
#
# Permission is hereby granted, free of charge, to any person obtaining a copy
# of this software and associated documentation files (the "Software"), to deal
# in the Software without restriction, including without limitation the rights
# to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
# copies of the Software, and to permit persons to whom the Software is
# furnished to do so, subject to the following conditions:
#
# The above copyright notice and this permission notice shall be included in all
# copies or substantial portions of the Software.
#
# THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
# IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
# FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
# AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
# LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
# OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE
# SOFTWARE.

# Below is the list of outside modules you'll be using in your skill.
# They might be built-in to Python, from mycroft-core or from external
# libraries.  If you use an external library, be sure to include it
# in the requirements.txt file so the library is installed properly
# when the skill gets installed later by a user.

from adapt.intent import IntentBuilder
from mycroft.skills.core import MycroftSkill, intent_handler
from mycroft.util.log import LOG

# For making REST requests
import urllib.request

# For multicast / UPnP
import socket
import struct

# Each skill is contained within its own class, which inherits base methods
# from the MycroftSkill class.  You extend this class as shown below.

class RokuSkill(MycroftSkill):

	# The constructor of the skill, which calls MycroftSkill's constructor
	def __init__(self):
		super(RokuSkill, self).__init__(name="RokuSkill")

		self.rokuSerial = ""
		self.rokuLocation = ""
		self.rokuStaticAddress = ""

	def initialize(self):
		# Check and then monitor for web settings
		self.settings.set_changed_callback(self.on_websettings_changed)
		self.on_websettings_changed()

	def on_websettings_changed(self):
		self.rokuSerial = self.settings.get("serial", "")
		self.rokuStaticAddress = self.settings.get("staticAddress", "")

		self.findRoku();

	def parseSearchResponse(self, data):
		lines = data.decode("utf-8").split('\n')

		if (lines[0].strip() != "HTTP/1.1 200 OK"):
			return None

		isRoku = False
		location = ""
		usn = ""

		for line in lines:
			if (len (line) < 3):
				continue

			index = line.find(":")

			if (index < 1 or index >= len (line) - 1):
				continue

			key = line[:index].strip().lower()
			value = line[index+1:].strip()

			if (key == "st"):
				isRoku = value.lower() == "roku:ecp"

				if (not isRoku): # No point in looking if it's not the roku
					break
			elif (key == "location"):
				location = value
			elif (key == "usn"):
				usn = value
		
		if (not isRoku):
			return None

		return (location, usn)

	def findRoku(self):
		if (self.rokuStaticAddress != ""):
			self.rokuLocation = self.rokuStaticAddress

		MCAST_GRP = '239.255.255.250'
		MCAST_PORT = 1900

		SSDP_QUERY = b"M-SEARCH * HTTP/1.1\n" \
		             b"Host: 239.255.255.250:1900" \
					 b"\nMan: \"ssdp:discover\"" \
					 b"\nST: roku:ecp\n\n"

		sendSock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM, socket.IPPROTO_UDP)
		sendSock.setsockopt(socket.IPPROTO_IP, socket.IP_MULTICAST_TTL, 32)
		sendSock.bind(('', 0));
		sendSock.settimeout(1.0);

		sendSock.sendto(SSDP_QUERY, (MCAST_GRP, MCAST_PORT))

		found = False

		try:
			while 1:
				data, addr = sendSock.recvfrom(2048)
				response = self.parseSearchResponse(data)

				if (response == None):
					LOG.error("Failed to parse response")
					continue

				if (response[1].find(self.rokuSerial) >= 0):
					self.rokuLocation = response[0]
					LOG.info("Found Roku " + response[1] + " at " + self.rokuLocation)
					found = True
					break

		except socket.timeout:
			if not found:
				LOG.error("No roku found")
		except Exception as e:
			LOG.exception("Error finding roku: " + str(e))


	def get_intro_message (self):
		return self.translate("intro")

	@intent_handler(IntentBuilder("").require("Show").require("Source"))
	def handle_roku_show_intent(self, message):
		# If we haven't found the roku, try finding it again right now
		if (self.rokuLocation == ""):
			self.findRoku()
		# If we still can't find it, then just report a failure
		if (self.rokuLocation == ""):
			self.speak_dialog("failure")
			return

		provider = ""
		src = message.data["Source"]

		# TODO: A list of providers comes from http://<address>:8060/query/apps
		#  In the future, could query this at startup, and then dynamically add
		#  the available sources to the list of providers. For now, just hard coding
		#  some popular ones.
		if src == "netflix":
			provider = "12"
		elif src == "amazon":
			provider = "13"
		elif src == "youtube":
			provider = "837"
		elif src == "tiny desk concerts":
			provider = "41305"
		elif src == "tune in" or src == "tunein":
			provider = "1453"
		elif src == "plex":
			provider = "13535"
		elif src == "disney plus":
			provider = "291097"
		elif src == "hbo":
			provider = "61322"
		else:	# Roku
			provider = ""

		if provider != "":
			provider = "&provider-id=" + provider

		keyword=self._extract_show(message)

		url = '{}search/browse?keyword={}{}&launch=true&match-any=true'.format (self.rokuLocation, keyword.replace(" ", "%20"), provider)
		
		LOG.info("Roku API request: " + url)
		
		try:
			postdata = urllib.parse.urlencode({}).encode()
			req = urllib.request.urlopen(url, data=postdata)
		except:
			self.speak_dialog("failure")
			return;

		self.speak_dialog("playing", data={"show": keyword, "source": src})

	def _extract_show(self, message):
		utterance = message.data["utterance"]
		utterance = utterance.replace(message.data["Show"], "")
		utterance = utterance.replace(message.data["Source"], "")

		# strip out other unimportant words
		common_words = self.translate_list("common_words");

		for words in common_words:
			utterance = utterance.replace(words, "")

		# Replace duplicate spaces
		utterance = utterance.replace("  ", " ")

		return utterance.strip();

	# The "stop" method defines what Mycroft does when told to stop during
	# the skill's execution. In this case, since the skill's functionality
	# is extremely simple, there is no need to override it.  If you DO
	# need to implement stop, you should return True to indicate you handled
	# it.
	#
	# def stop(self):
	#    return False

# The "create_skill()" method is used to create an instance of the skill.
# Note that it's outside the class itself.
def create_skill():
	return RokuSkill()
