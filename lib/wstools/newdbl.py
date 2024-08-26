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
from shutil import copyfile
from datetime import datetime
import time
from time import mktime
from zipfile import ZipFile
import logging

logger = logging.getLogger(__name__)

dblurl = "https://api.thedigitalbiblelibrary.org"
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

def process_projects(filelist, filterLangCode=None):
    for filename in filelist:
        if filename.endswith('.zip'):   # and os.path.isfile(filename)
            basename = os.path.basename(filename)
            langCode, fileid = basename.split("_")
            if filterLangCode is not None and langCode != filterLangCode:
                continue
            yield (filename, langCode)

def getdblkeys():
    try:
        import keyring
    except ImportError:
        pass
    else:
        try:
            key1 = keyring.get_password("DBL", "key1")
            key2 = keyring.get_password("DBL", "key2")
            if key1 is not None and key2 is not None:
                return (key1, key2)
        except keyring.errors.NoKeyringError:
            pass

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
        self.api_token = api_token.lower()
        self.private_key = private_key.lower()

    def __call__(self, r):
        r.headers[self.authorization_header] = self.make_authorization_header(r)
        return r

    def make_authorization_header(self, request):
        mac = hmac.new(self.api_token.encode("utf-8"), None, hashlib.sha1)
        mac.update(bytes(self.signing_string_from_request(request), 'utf-8)'))
        mac.update(self.private_key.lower().encode("utf-8"))
        tokenStr = self.api_token
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

def doone(a):
    a[0].downloadOneEntry(*a[1:])

class DBLReader(object):
    def __init__(self, key1 = None, key2 = None):
        if key1 is None or key2 is None:
            key1, key2 = getdblkeys()
        self.secretKey = key2
        self.auth = DBLAuthV1(key1, key2)

    def download(self, downloadDir, lang=None, skiplangs=['en', 'eng'], nozips=False, mapfile=None, pool=None, owned=True):
        entryfpath = os.path.join(downloadDir, "entries.json")
        if lang is None and os.path.exists(entryfpath):
            with open(entryfpath) as inf:
                outEntries = json.load(inf)
        else:
            outEntries = {}
        entries, httpResult = self.getjson(dblurl+'/api/entries') # + ('' if owned else '/visible_entries'))
        if httpResult != 200:
            logging.error("ERROR in obtaining DBL entries; HTTP response code = ", httpResult)
            return
        if mapfile is not None:
            with open(mapfile) as inf:
                ptxmap = json.load(inf)
        else:
            ptxmap = {'PTX': {}, 'lang': {}}
        jobs = []
        for e in entries['entries']:
            l = e['languageCode']
            langcode = ptxmap['PTX'].get(e['idParatextName'], ptxmap['lang'].get(l, l))
            if langcode == "":
                continue
            eid = e['id']
            key = "{}_{}".format(langcode, eid)
            outEntries[key] = e
            if nozips or e['entrytype'] != 'text':
                continue
            if (lang is not None and lang != langcode) \
                    or langcode in skiplangs:
                continue
            jobs.append((self, eid, langcode, downloadDir, nozips, logger))
        if pool is None:
            for j in jobs:
                doone(j)
        else:
            print("doing {} jobs in parallel".format(len(jobs)))
            list(pool.imap_unordered(doone, jobs))
        entryfname = "entries_{}.json".format(lang) if lang is not None else "entries.json"
        with open(os.path.join(downloadDir, entryfname), "w") as outf:
            json.dump(outEntries, outf, indent=2)
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

    def getdata(self, url, length=0):
        exti = url.rfind(".")
        ext = url[exti+1:] if exti > -1 else "dat"
        response = requests.get(url, auth=self.auth, headers=self._fileHeaders(ext, length))
        if response.status_code == 200:
            return (response.content, response.status_code)
        else:
            return (None, response.status_code)

    def getLicenses(self):
        return self.getjson(dblurl+'/api/licenses')

    def downloadOneEntry(self, entryId, langCode, downloadPath, nozips=False, logger=None):
        # Get the metadata that includes the license key for reading.
        fname = "{}_{}.zip".format(langCode, entryId)
        fpath = os.path.join(downloadPath, fname)
        if os.path.exists(fpath):
            return
        filesUrl = dblurl+'/api/entries/' + entryId + "/revisions/latest/license/owner"
        try:
            filesList, httpResult = self.getjson(filesUrl)
        except requests.exceptions.ConnectionError:
            if logger is not None:
                logger.error("Timeout while trying to start {}".format(fpath))
            return
        if httpResult != 200:
            return
        if not nozips:
            if logger is not None:
                logger.info("Downloading: " + entryId + " - " + langCode)
            zfile = ZipFile(fpath, "w")
            for e in filesList['list']:
                length = int(e['size'])
                fname = e['uri']
                try:
                    (dat, result) = self.getdata("{}/{}".format(filesUrl, fname))
                except requests.exceptions.ConnectionError:
                    zfile.close()
                    os.unlink(fpath)
                    if logger is not None:
                        logger.error("Timeout while trying to load files for {}".format(fpath))
                    return
                if dat is not None:
                    zfile.writestr(fname, dat)
            zfile.close()
            if logger is not None:
                logger.info("Finished: " + entryId + " - " + langCode)
        return

    def _jsonHeaders(self):
        return {'Date': format_date_time(mktime(datetime.now().timetuple())),
                'Content-Type': 'application/json'}

    def _fileHeaders(self, ext="txt", length=0):
        mimeTypes = {'zip': 'application/zip', 'xml': "text/xml", 'usx': 'text/xml', 'ldml': 'text/xml'}
        # or application/octet-stream?
        return {'Content-Type': mimeTypes.get(ext, 'text/plain'),
                'Content-Transfer-Encoding': 'binary,gzip,deflate',
                'Content-Length': str(length)}

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

    def __init__(self):
        self.exemplars = Exemplars()
        # For DBL data, we have our doubts as to whether frequency is a good indicator of whether a character
        # is main or auxiliary. So set the threshold to zero which will treat all characters found as main.
        self.project = None
        self.publishable = set()
        self.main_text = ('ip', 's', 'p', 'q')

    def open_project(self, zipfilename):
        """Open a DBL project zip file."""
        self.project = zipfile.ZipFile(zipfilename, 'r')
        # self.corpus = codecs.open(zipfilename + '.main.txt', 'w', encoding='utf-8')

    def namelist(self):
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
        for marker in list(root):
            style = marker.get('style')
            if style in self.publishable and style.startswith(self.main_text):
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
                    copyfile(filename, newname)
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
            yield element.text
        for e in element:
            for se in self.iter_main_text(e):
                yield se
            if e.tail:
                yield e.tail

    def close_project(self):
        """Close a DBL project."""
        self.project.close()
        # self.corpus.close()

def exceptions():

# putting this here so I can pull it into the other modules in the scripts directory

    skipfilesmap= {
        # dbl files to skip over. Use key to briefly describe why it would be skipped
        "bwu_23924b4088bd455f.zip": "older, hacked font version of other bwu file",
        "kus_aa7bfc87e2d146e9.zip":"older, hacked font version of kus bwu file",
        "ptu_508d69aca227e09a.zip":"same translation as the other ptu file, just older with less books in it",
        "qvw_4682b4576f7f666f.zip":"slightly older NT version of the other qvw (which is OT). Using other one bc its files are nicer",
    }

    knownvarsmap= {
        # dbl files that we have previously discovered are variants but aren't labeled as such in any of the files
        #current key names are placeholders, rn I'm just finding which would dupe
        #this needs to be called AFTER langtags check or otherwise skip the langtags appropriate check bc some of these aren't in langtags
        "acr_7881095a69332502.zip":'acr-x-rabinal',
        "acr_2fb7cabcc2144633.zip":"acr-x-trabinal", #traditional orthography. formerly tagged as -x-rabinal-trad
        "acr_f39e0b553b5b6e1e.zip":"acr-x-cubulco",
        "aoj_9b2f4522c94167b3.zip":"aoj-x-filifita",
        "aoj_e1b773c63b9b23de.zip":"aoj-x-balif",
        "ape_0e5e9ab5304a71df.zip":"ape-x-coastal",
        "ape_9adf28ef3e43803b.zip":"ape-x-mountain",
        "avu_25b22b576c35c0a2.zip":"avu",   # file has this under SD instead of the default SS region but there is functionally no diff
        "buu_9dfa86fef49a2749.zip":"buu-x-koya",    #Budu-Koya, rolv code 19443 
        "buu_7f38828c4ca2f6ec.zip":"buu-x-ineta",         #Budu-Nita
        #"bwu_adfa3f511e02d362.zip":"bwu",
        "cak_0c58bc770fea1f13.zip":"cak-x-xenacoj",
        "cak_78df9d2017796a6a.zip":"cak-x-swestern", #aka yepocapa 
        "cak_a4c5eb163eacc4fe.zip":"cak-x-central",
        "cak_a804bbc16f5648c6.zip":"cak-x-subsa",    #aka cak santa maria
        "cak_ba8af875c3c81f92.zip":"cak-x-subsu",   # aka cak southern
        "cak_bc4e6ea72ebcd70a.zip":"cak-x-eastern", #aka cak oriental
        "cak_c4fe9e2ee5c9478b.zip":"cak-x-subcm",   #aka surcentral. pretty sure that's subcm (4023 chimaltenago)
        "cak_edc84e947196a225.zip":"cak-x-subso",   #aka western. pretty sure that's subso (4024 solola)
        "cbs_bfe3d27ca02d8188.zip":"cbs-BR",
        "ctu_fc58a81f91b61c65.zip":"ctu-x-tumbala",
        "ctu_312b0d1e64e9e427.zip":"ctu-x-tila",
        "dhg_9f72b29d8a4d0cd8.zip":"dhg-x-wangurri",
        "gfk_83abc8c1746443c3.zip":"gfk-x-sokarek",  #sokarek dialect rolv id 21925
        "gfk_eeaf12df03835eb2.zip":"gfk-x-hinsaal",   # hinsaal dialect, rolv id 21926
        "hus_05749a20390d4b57.zip":"hus-x-central",  #huasteco veracruz, rolv code 04681
        "hus_4debd996d0f50e67.zip":"hus-x-potosino",   #Huastec San Luis Potosi
        "ixl_2bac6224ab47bab8.zip":"ixl-x-cotzal",
        "ixl_2dad83033884a3ad.zip":"ixl-x-nebaj",
        "kmh_3de6c420cb00e851.zip":"kmh-x-minimib",   
            #NOT IN LANGTAGS OR ROLV? Very closely related to the Kopon (kpw) language which does have a rolv Minimib dialect (21176)
        "knv_cd88ca9cb083c101.zip":"knv-x-flyriver",
        "knv_74ea3f410729934b.zip":"knv-x-aramia",
        "kqe_7876fc7be8a234f1.zip":"kqe-x-east",
        "kqe_9396bdab17afda48.zip":"kqe-x-west",
        #"kus_333a4a06309f5935.zip":"kus",   
        "lwo_94f55365a50fb16d.zip": "lwo",  # file has this under ZA instead of the default SS region but there is functionally no diff
        "mam_8eb38973d944f48a.zip":"mam-x-central",
        "mam_925bffd8dc536fee.zip":"mam-x-todos",   #mam todos santos, rolv 03470
        #"mbb":"mbb"    # there are two projects for mbb, but one is a NT and one is an OT, produced around the same time and with identical ldml & lds file contents, only dif would be exemplars from actual text
        "nhx_d38a664622353792.zip":"nhx-x-tatahui",
        #"noa_237c316a234a0fa7.zip":"noa", # "original orthography"
        "noa_5f19908d3d3695c1.zip":"noa-x-alt", # "alternate orthography", might get new tag name
        "okv_78b96b766ccc69b2.zip":"okv-x-etija", #Etija dialect, rolv code 15341
        "okv_804cc342b7cc775a.zip":"okv-x-ehija", #Ehija dialect, rolv code 15340
        #"ptu_e147c0d35d7dd600.zip":"ptu",
        "quc_dd5c5f7428bdbc7d.zip":"quc-x-trad",     #"traditional orthography"
        #"qvw_2b2b53c89ed39448.zip":"qvw",   
        "tuc_79eafcc60f337d8c.zip":"tuc-x-oov",
        "tuc_00f8a1a8be6d4cbd.zip":"tuc-x-tuam",
        "tuo_9e63cdeff066ea65.zip":"tuo-CO",
        "tzj_28b49503236ab541.zip":"tzj-x-western",
        "tzo_89a655d8cecbd0b5.zip":"tzo-x-zinacntn",
        "tzo_d3c1a6a5b1a6d906.zip":"tzo-x-huixtan",
        "tzo_d2852d0e5004eee9.zip":"tzo-x-sanandre",
        "wed_017a5237548af856.zip":"wed-x-topura",
        "xbi_1d2500c097ee17fc.zip":"xbi-x-western",   #Kombio Wampukuamp, aka west-central kombio (rolv 12184)
        "xbi_6143d8c5bae3a41f.zip":"xbi-x-south",   #Kombio Yanimoi, aka south kombio (rolv 12183)
        "xsm_78b5ca615ee7f539.zip":"xsm-BF"   #Burkina Faso orthography
    }

    return (skipfilesmap, knownvarsmap)


if __name__ == '__main__':
    main()
