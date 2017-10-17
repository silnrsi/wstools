#!/usr/bin/python

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
import sys
import codecs
import zipfile

try:
    from sldr.ldml_exemplars import Exemplars
except ImportError:
    sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..', '..', 'sldr', 'python', 'lib')))
    from sldr.ldml_exemplars import Exemplars


def main():
    pass


class DBL(object):

    def __init__(self):
        self.exemplars = Exemplars()
        self.project = None

    def load(self, zipfilename):
        """Open a DBL project zip file."""
        self.project = zipfile.ZipFile(zipfilename, 'r')

    def process(self):
        """Process a DBL project."""
        for name in self.project.namelist():
            if name.endswith('.usx'):
                usx = self.project.open(name, 'r')
                for line in usx:
                    self.exemplars.process(line)

    def analyze(self):
        """Analyze a DBL project."""
        self.project.close()
        self.exemplars.analyze()

if __name__ == '__main__':
    main()
