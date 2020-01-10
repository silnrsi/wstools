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
# import codecs
import zipfile
import xml.etree.ElementTree as ET
from shutil import copyfile

try:
    from sldr.ldml_exemplars import Exemplars
except ImportError:
    sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..', '..', 'palaso-python', 'lib', 'palaso')))
    #newDir = os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..', '..', 'palaso-python', 'lib', 'palaso'))
    #sys.path.insert(-1, newDir)
    from sldr.ldml_exemplars import Exemplars


def main():
    pass


class DBL(object):

    def __init__(self):
        self.exemplars = Exemplars()
        # For DBL data, we have our doubts as to whether frequency is a good indicator of whether a character
        # is main or auxiliary. So set the threshold to zero which will treat all characters found as main.
        self.exemplars.frequent = 0.0
        self.project = None
        self.publishable = set()
        self.main_text = ('ip', 's', 'p', 'q')

    def open_project(self, zipfilename):
        """Open a DBL project zip file."""
        self.project = zipfile.ZipFile(zipfilename, 'r')
        # self.corpus = codecs.open(zipfilename + '.main.txt', 'w', encoding='utf-8')

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

    def process_project(self):
        """Process a DBL project."""

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
                    self.exemplars.process(text)
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

    def analyze_projects(self):
        """Analyze DBL project(s)."""
        self.exemplars.analyze()


if __name__ == '__main__':
    main()
