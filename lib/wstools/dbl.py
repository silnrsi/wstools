#!/usr/bin/python3

# Redistribution and use in source and binary forms, with or without
# modification, are permitted provided that the following conditions
# are met:
# 1. Redistributions of source code must retain the above copyright
#    notice, this list of conditions and the following disclaimer.
# 2. Redistributions in binary form must reproduce the above copyright
#    notice, this list of conditions and the following disclaimer in the
#    documentation and/or other materials provided with the distribution.
# 3. Neither the name of the University nor the names of its contributors
#    may be used to endorse or promote products derived from this software
#    without specific prior written permission.
#
# THIS SOFTWARE IS PROVIDED BY THE REGENTS AND CONTRIBUTORS ``AS IS'' AND
# ANY EXPRESS OR IMPLIED WARRANTIES, INCLUDING, BUT NOT LIMITED TO, THE
# IMPLIED WARRANTIES OF MERCHANTABILITY AND FITNESS FOR A PARTICULAR PURPOSE
# ARE DISCLAIMED.  IN NO EVENT SHALL THE REGENTS OR CONTRIBUTORS BE LIABLE
# FOR ANY DIRECT, INDIRECT, INCIDENTAL, SPECIAL, EXEMPLARY, OR CONSEQUENTIAL
# DAMAGES (INCLUDING, BUT NOT LIMITED TO, PROCUREMENT OF SUBSTITUTE GOODS
# OR SERVICES; LOSS OF USE, DATA, OR PROFITS; OR BUSINESS INTERRUPTION)
# HOWEVER CAUSED AND ON ANY THEORY OF LIABILITY, WHETHER IN CONTRACT, STRICT
# LIABILITY, OR TORT (INCLUDING NEGLIGENCE OR OTHERWISE) ARISING IN ANY WAY
# OUT OF THE USE OF THIS SOFTWARE, EVEN IF ADVISED OF THE POSSIBILITY OF
# SUCH DAMAGE.

import os
import os.path
import sys
import requests, hmac, hashlib, json
# import codecs
import zipfile, logging
import xml.etree.ElementTree as ET
from shutil import copy
from datetime import datetime
from wsgiref.handlers import format_date_time
from time import mktime

dblurl='https://api.thedigitalbiblelibrary.org'

try:
    from sldr.ldml_exemplars import Exemplars
except ImportError:
    sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..', '..', 'palaso-python', 'lib', 'palaso')))
    #newDir = os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..', '..', 'palaso-python', 'lib', 'palaso'))
    #sys.path.insert(-1, newDir)
    from sldr.ldml_exemplars import Exemplars

# From wsgiref.handlers - HTTP date/time formatting always English!
_weekdayname = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]
_monthname = [None, # Dummy so we can use 1-based month numbers
              "Jan", "Feb", "Mar", "Apr", "May", "Jun",
              "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"]

def format_date_time(timestamp):
    year, month, day, hh, mm, ss, wd, y, z = time.gmtime(timestamp)
    return "%s, %02d %3s %4d %02d:%02d:%02d GMT" % (
        _weekdayname[wd], day, _monthname[month], year, hh, mm, ss
    )

def process_projects(files, filterLangCode=None):
    for filename in files:
        if filename.endswith('.zip'):   # and os.path.isfile(filename)
            basename = os.path.basename(filename)
            i = basename.find("_")
            if i < 0:
                continue
            langCode = basename[0:i]

            if filterLangCode is not None and langCode != filterLangCode \
                    and not langCode.startswith(filterLangCode+"-"):
                continue
            yield (filename, langCode)

def getdblkeys():
    try:
        import keyring
    except ImportError:
        pass
    else:
        key1 = keyring.get_password("DBL", "key1")
        key2 = keyring.get_password("DBL", "key2")
        if key1 is not None and key2 is not None:
            return (key1, key2)

    try:
        import dblauthkey
    except ImportError:
        pass
    else:
        return dblauthkey.authkey()

    try:
        import configparser
        import appdirs
    except ImportError:
        pass
    else:
        d = appdirs.user_config_dir("DBL", "SIL")
        cfile = os.path.join(d, "authkey.ini")
        if os.path.exists(cfile):
            config = configparser.ConfigParser()
            config.read([cfile])
            key1 = config.get("keys", "key1")
            key2 = config.get("keys", "key2")
            if key1 is not None and key2 is not None:
                return (key1, key2)

    return (None, None)

class DBLAuthV1(requests.auth.AuthBase):
    authorization_header = 'X-DBL-Authorization'

    def __init__(self, api_token, private_key):
        super(DBLAuthV1, self).__init__()
        self.api_token = bytes(api_token.lower(), "utf-8")
        self.private_key = bytes(private_key.lower(), "utf-8")

    def __call__(self, r):
        r.headers[self.authorization_header] = self.make_authorization_header(r)
        return r

    def make_authorization_header(self, request):
        mac = hmac.new(self.api_token, None, hashlib.sha1)
        mac.update(bytes(self.signing_string_from_request(request), 'utf-8)'))
        mac.update(self.private_key.lower())
        tokenStr = self.api_token.decode('utf-8')
        return 'version=v1,token=%s,signature=%s' % (tokenStr, mac.hexdigest().lower())

    def signing_string_from_request(self, request):
        dbl_header_prefix = 'x-dbl-'
        signing_headers = ['content-type', 'date']

        method = request.method
        # use request uri, but not any of the arguments.
        path = request.path_url.split('?')[0]
        collected_headers = {}

        for key, value in request.headers.items():
            if key == self.authorization_header:
                continue
            k = key.lower()
            if k in signing_headers or k.startswith(dbl_header_prefix):
                collected_headers[k] = value.strip()

        # these keys get empty strings if they don't exist
        if 'content-type' not in collected_headers:
            collected_headers['content-type'] = ''
        if 'date' not in collected_headers:
            collected_headers['date'] = ''

        sorted_header_keys = sorted(collected_headers.keys())

        buf = "%s %s\n" % (method, path)
        for key in sorted_header_keys:
            val = collected_headers[key]
            if key.startswith(dbl_header_prefix):
                buf += "%s:%s\n" % (key, val)
            else:
                buf += "%s\n" % val
        return buf


class DBLReader(object):
    def __init__(self, key1 = None, key2 = None):
        if key1 is None or key2 is None:
            key1, key2 = getdblkeys()
        self.secretKey = key2
        self.auth = DBLAuthV1(key1, key2)

    def download(self, downloadDir, lang=None, skiplangs=['en', 'eng', 'es'], update=False, allids=False, srcdir=None):
        entriesDict = self.getEntries(allids=allids)
        if srcdir is not None:
            srcs = set(os.listdir(srcdir))
        else:
            srcs = set()
        if isinstance(entriesDict, int):
            logging.error("ERROR in obtaining DBL entries; HTTP response code = ", entriesDict)
            return False
        else:
            for (entryId, entryInfo) in entriesDict.items():
                (entryLangCode, entryAccessType) = entryInfo
                testlang = entryLangCode + "-"
                testlang = testlang[:testlang.find("-")]
                fname = entryLangCode+"_"+entryId+".zip"
                if (lang is not None and lang != entryLangCode and not entryLangCode.startswith(lang+"-")) \
                        or testlang in skiplangs:
                    logging.debug("Skipping (language): "+fname)
                    continue
                if update and os.path.exists(os.path.join(downloadDir, fname)):
                    logging.debug("Skipping (already have): " + fname)
                    continue
                if fname in srcs:
                    logging.debug("Copying {} from {} to {}".format(fname, srcdir, downloadDir))
                    copy(os.path.join(srcdir, fname), downloadDir)
                    continue
                logging.info("Downloading: " + fname)
                self.downloadOneEntry(entryId, entryLangCode, entryAccessType, downloadDir)
        return True
        

    def testAccess(self):
        response = requests.get(dblurl,
                                auth=self.auth, headers=self._jsonHeaders())
        return response.status_code

    def getjson(self, url):
        response = requests.get(url, auth=self.auth, headers=self._jsonHeaders())
        if response.status_code == 200:
            return (json.loads(response.content), response.status_code)
        else:
            return (None, response.status_code)

    def getLicenses(self):
        return self.getjson(dblurl+'/api/licenses')

    def getEntries(self, allids=False):
        fullResult = {}
        httpResult = 1000
        #accessTypeKeys = ['publishable', 'public', 'open_access', 'owned']
        accessTypeKeys = ['owned']
        alllangs = set()
        for accessType in accessTypeKeys:
            #entriesDict, httpResult = self.getjson(dblurl+'/api/' + accessType + '_entries_list')
            entriesDict, httpResult = self.getjson(dblurl+'/api/entries')
            if httpResult == 200:
                for entry in entriesDict['entries']:
                    id = entry['id']
                    langCode = entry['languageLDMLId']
                    if not len(langCode):
                        langCode = entry['languageCode']
                    if langCode in alllangs:
                        if allids:
                            langCode += "-x-" + entry['nameAbbreviation']
                        else:
                            continue
                    alllangs.add(langCode)
                    if id in fullResult:
                        (bogus, oldAccess) = fullResult[id]
                        if oldAccess != accessType:
                            logging.info("changing " + langCode + "_" + id + " from " + oldAccess + " to " + accessType)
                    fullResult[id] = (langCode, accessType)
                return fullResult
            else:
                return httpResult

    def downloadOneEntry(self, entryId, langCode, accessType, downloadPath):
        # Get the metadata that includes the license key for reading.
        entryMetaData, httpResult = self.getjson(dblurl+'/api/entries/' + entryId)
        if httpResult != 200:
            return httpResult
        licenses = entryMetaData.get('licenses', '')
        if accessType == 'owned':
            licenseId = "owner"
        elif len(licenses) > 0:
            licenseId = str((licenses[0])['id'])
        else:
            logging.warn(langCode + "_" + entryId + " - no licenses")
            return 403  # forbidden

        entryUrl = dblurl+'/api/entries/' + entryId + "/revision/latest/license/" + licenseId
        entryData, response = self.getjson(entryUrl)
        if response != 200:
            logging.error(langCode + " - can't access files")
            return response

        result = None
        urlList = entryData['list']
        downloadZip = False
        for url in urlList:
            path = url['uri']
            downloadUrl = None
            ext = path[path.rfind("."):]
            if ext == ".usx":
                downloadZip = True
                break
            if ext in ('.lds', '.ssf', '.ldml'):
                key = ext[1:]
            if ext in ('.sfm', '.usfm', '.ptx'):
                logging.warn("Found SFM file!!")

        if downloadZip:
            url = entryData['href'] + "/license/" + licenseId + ".zip"
            response = requests.get(url, auth=self.auth, headers=self._jsonHeaders())
            if response.status_code == 200:
                downloadFileName = langCode + "_" + entryId + ".zip"
                self._saveDownloadedFile(downloadPath, downloadFileName, response.content)
                result = downloadPath + "/" + downloadFileName
                logging.debug(langCode + " - DOWNLOADED " + downloadFileName)
            else:
                logging.warn(langCode + " - can't download zip file: {}, {}".format(response.status_code, url)) 
        else:
            logging.warn(langCode + " - no usx files")
        return result

    def _jsonHeaders(self):
        return {'Date': format_date_time(mktime(datetime.now().timetuple())),
                'Content-Type': 'application/json'}

    def _saveDownloadedFile(self, dirPath, filename, contents):
        if not os.path.exists(dirPath):
            os.makedirs(dirPath)
        fullname = os.path.join(dirPath, filename)
        with open(fullname, "wb") as outf:
            outf.write(contents)

#end of class DBLReader
def main():
    pass


class DBL(object):
    def __init__(self, zipfilename):
        self.project = None
        self.publishable = set()
        self.main_text = ('ip', 's', 'p', 'q')
        self.project = zipfile.ZipFile(zipfilename, 'r')

    def namelist(self):
        """ Return the zip file namelist """
        return self.project.namelist()

    def query_project(self):
        """Query a DBL project for ad-hoc information.

        The information will be used to help write code,
        and not be used in production.
        """

        # Find stylesheets.
        found = False
        for filename in self.project.namelist():
            if os.path.basename(filename) == 'styles.xml':
                found = True
                print(filename)
        if not found:
            print("not found!")

    def analyze_text(self):
        """Analyse the scripture text. Iterates yielding text strings"""

        # Read stylesheet.
        found_stylesheet = False
        for filename in self.project.namelist():
            if os.path.basename(filename) == 'styles.xml':
                found_stylesheet = True
                style = self.project.open(filename, 'r')
                self._read_stylesheet(style)
        if not found_stylesheet:
            raise IOError('stylesheet not found')

        # Process text data.
        for filename in self.project.namelist():
            if filename.endswith('.usx'):
                usx = self.project.open(filename, 'r')
                for text in self._process_usx_file(usx):
                    yield text
                    # self.exemplars.process(text)
                    # self.corpus.write(text + '\n')

    def _read_stylesheet(self, style):
        """Read stylesheet and record which markers are publishable."""
        tree = ET.parse(style)
        for marker in tree.findall('style'):
            if marker.get('publishable') == 'true':
                self.publishable.add(marker.get('id'))

    def _process_usx_file(self, usx):
        """Process one USX file."""
        tree = ET.parse(usx)
        root = next(tree.iter())
        publish = list(self.publishable)
        arabic_style_ids = {'ك':'id', 'عك':'h', 'م':'imt', 'مف':'ip', 'ص':'c', 'ي':'v', 'ف':'p', 'ف 1':'m', 'ف 2':'nb', 'ش':'q', 'ش1':'q1', 'ش2':'q2', 'س':'qs', 'شغ':'b', 'عر':'mt', 'عر1':'mt1', 'عر2':'mt2', 'عق':'ms', 'عق1':'mr', 'ع':'s', 'ع1':'s1', 'ع2':'s2', 'عش':'r', 'عم':'sp', 'عج':'d', 'ت':'f', 'تش':'fr', 'تن':'ft', 'تنش':'fq', 'تشم':'x', 'تشل':'xo', 'تشت':'xt', 'صو':'fig'}   
            # specifically for arq which has a stylesheet with some arabic ids for some reason
        for x in publish:
            if x in arabic_style_ids.keys():
                self.publishable.pop()
                self.publishable.add(arabic_style_ids[x])
        for marker in list(root):
            style = marker.get('style')
            if style in self.publishable and (style.startswith(self.main_text) or style == ('m')):
                for text in self._get_text(marker):
                    yield text
        usx.close()

    def file_contents_with_ext(self, ext):
        """Return the contents of the file with the given extension, if any."""
        for filename in self.project.namelist():
            if filename.endswith('.'+ext):
                contents = self.project.open(filename, 'r')
                return contents
        return None

    def extract_file_with_ext(self, ext, newname=None):
        """Return the contents of the file with the given extension, if any."""
        for filename in self.project.namelist():
            if filename.endswith('.' + ext):
                self.project.extract(filename)
                if newname is not None:
                    if os.path.exists(newname):
                        os.remove(newname)
                    copy(filename, newname)
                    os.remove(filename)
                return

    def extract_file(self, filename):
        if filename in self.project.namelist():
            self.project.extract(filename)
            return True
        else:
            return False

    def _get_text(self, element):
        """Extract all text from an ET Element."""
        # for text in element.itertext():
        for text in self.iter_main_text(element):
            yield text.strip()

    def iter_main_text(self, element):
        """Extract all text (except notes) from an ET Element."""
        if element.tag == 'note':
            return
        if element.text:
            if element.text.strip():
                yield element.text
        if element.tail:
            if element.tail.strip():
                yield element.tail
        for e in element:
            for se in self.iter_main_text(e):
                yield se

    def close_project(self):
        """Close a DBL project."""
        self.project.close()
        # self.corpus.close()

if __name__ == '__main__':
    main()
