#!/usr/bin/python3

import csv

suggestions = dict()


def read_font_data(data_file_name):
    """Read CSV data file"""
    font_sources = ('WSTech primary', 'NLCI', 'Microsoft', 'Other', 'Noto Sans', 'Noto Serif', 'WSTech secondary')
    with open(data_file_name, 'r', newline='') as data_file:
        reader = csv.DictReader(data_file)

        for row in reader:

            # Construct tag
            script = row['Code']
            tag = script
            for region in row['Region'].split(', '):
                if region != '':
                    tag = script + '_' + region

                # Assemble list of fonts for the tag
                fonts = list()
                for font_source in font_sources:
                    font = row[font_source]
                    if font:
                        if ',' in font:
                            for multiple_font in font.split(', '):
                                fonts.append(multiple_font)
                        else:
                            fonts.append(font)
                if len(fonts) > 0:
                    suggestions[tag] = fonts
