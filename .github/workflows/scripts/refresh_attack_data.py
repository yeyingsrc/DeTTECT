from stix2 import datastore, Filter
from requests import exceptions
from attackcti import attack_client
from shutil import copyfile
import json
import re
from logging import getLogger, ERROR as LOGERROR
getLogger("taxii2client").setLevel(LOGERROR)

FILE_PATH_EDITOR_DATA = '../../../editor/src/data/'
FILE_PATH_CLI_DATA = '../../../data/'
FILE_PATH_EDITOR_CONSTANTS = '../../../editor/src/constants.js'
FILE_PATH_WIKI = '../../../wiki/'

FILE_DATA_SOURCES = 'data_sources.json'
FILE_TECHNIQUES = 'techniques.json'
FILE_SOFTWARE = 'software.json'
FILE_DATA_SOURCES_PLATFORMS = 'data_source_platforms.json'

FILE_WIKI_DATA_SOURCE_PLATFORMS = 'Data-sources-per-platform.md'

MATRIX_ENTERPRISE = 'mitre-attack'
MATRIX_ICS = 'mitre-ics-attack'

WIKI_TEXT = [
    'The below mapping from data sources/data components to platforms is created on the information provided by MITRE within the [data source objects](https://attack.mitre.org/datasources/). Also, note that the below is only listing data components that are actually referenced by a technique. Therefore it does not include all data components as referenced in the [data source YAML files](https://github.com/mitre-attack/attack-datasources).',
    '']


class ATTACKData():
    """
    Refresh the json data files for the DeTT&CT Editor and CLI
    """

    def __init__(self):
        try:
            self.mitre = attack_client()
        except (exceptions.ConnectionError, datastore.DataSourceError):
            print("[!] Cannot connect to MITRE's CTI TAXII server")
            quit()

        self.data_source_dict_enterprise = self._create_data_source_dict(MATRIX_ENTERPRISE)

        self.attack_cti_techniques_enterprise = self.mitre.get_enterprise_techniques()
        self.attack_cti_techniques_enterprise = self.mitre.remove_revoked(self.attack_cti_techniques_enterprise)
        self.attack_cti_techniques_enterprise = self.mitre.remove_deprecated(self.attack_cti_techniques_enterprise)

        self.attack_cti_software = self.mitre.get_software()
        self.attack_cti_software = self.mitre.remove_revoked(self.attack_cti_software)
        self.attack_cti_software = self.mitre.remove_deprecated(self.attack_cti_software)

    def execute_refresh_json_data(self):
        """
        Execute all methods to refresh all json data files for data source, techniques and software
        """
        data_components_enterprise = self._get_data_sources_from_dict(self.data_source_dict_enterprise)
        self._dump_data(data_components_enterprise, FILE_DATA_SOURCES)

        data_components_enterprise_platform_mapping = self._get_data_components_platform_mapping_from_dict(self.data_source_dict_enterprise)
        self._update_data(data_components_enterprise_platform_mapping, 'ATT&CK', FILE_DATA_SOURCES_PLATFORMS)

        techniques_enterprise = self._get_techniques(self.attack_cti_techniques_enterprise, MATRIX_ENTERPRISE)
        self._dump_data(techniques_enterprise, FILE_TECHNIQUES)

        software_enterprise = self._get_software(self.attack_cti_techniques_enterprise, MATRIX_ENTERPRISE)
        self._dump_data(software_enterprise, FILE_SOFTWARE)

    def execute_refresh_wiki(self):
        """
        Execute all methods to refresh this Wiki page 'Data-sources-per-platform.md'
        """
        markdown_lines = self._generate_markdown(self.data_source_dict_enterprise)
        self._write_to_wiki(markdown_lines, FILE_WIKI_DATA_SOURCE_PLATFORMS)

    def _get_platforms_constants(self, platforms_key):
        """
        Get the ATT&CK platforms from the provided kv pair in constants.js (used by the Editor)
        We only to this because we want to have the correct order which is already saved in the Editor
        :param platforms_key: value of the platforms key
        :return: list with ATT&CK platforms
        """
        with open(FILE_PATH_EDITOR_CONSTANTS, 'r') as f:
            data = f.read()
            platforms_str = re.search(platforms_key + ': \[.+\]', data).group(0)

        platforms_str = platforms_str.replace("'", '"')
        platforms_str = '{' + platforms_str + '}'
        platforms_str = platforms_str.replace(platforms_key, '"' + platforms_key + '"')

        platforms_json = json.loads(platforms_str)
        platforms = platforms_json[platforms_key][1:]  # remove 'all'

        return platforms

    def _generate_markdown(self, data_source_dict):
        """
        Generate the markdown for the Wiki page Data-sources-per-platform.md
        :param data_source_dict: a dict with the data sources as created by the function _create_data_source_dict
        :return: markdown text in a list
        """
        platforms = self._get_platforms_constants('PLATFORMS')
        data_sources_sorted = sorted(data_source_dict.keys())

        lines = WIKI_TEXT

        # create the table heading
        l1 = '| Data source | '
        for p in platforms:
            l1 += p + ' | '
        lines.append(l1)

        l2 = '|'
        for i in range(len(platforms) + 1):
            l2 += ' ---- |'
        lines.append(l2)

        # the first entries of the Markdown table will consist of the DeTT&CT data sources
        dds_json = None
        with open(FILE_PATH_CLI_DATA + FILE_DATA_SOURCES_PLATFORMS, 'r') as f:
            dds_json = json.load(f)['DeTT&CT']

        dds_per_platform = {}  # {dettect data source: set(platforms)}
        for p, ds in dds_json.items():
            for ds in ds:
                if ds not in dds_per_platform:
                    dds_per_platform[ds] = set()
                dds_per_platform[ds].add(p)

        for dds in sorted(dds_per_platform.keys()):
            dds_part_1 = dds.removesuffix(' [DeTT&CT data source]')
            url = 'DeTT&CT-data-sources#' + dds_part_1.replace(' ', '-')
            row = '| [' + dds_part_1 + '](' + url + ') *[DeTT&CT data source]* | '

            for p in platforms:
                if p in dds_per_platform[dds]:
                    row += ' X |'
                else:
                    row += '   |'

            lines.append(row)

        # add the ATT&CK data sources to the Markdown table
        for ds in data_sources_sorted:
            for dc in sorted(data_source_dict[ds]['data_components']):
                url = data_source_dict[ds]['wiki_url'] + '/#' + dc.replace(' ', '%20')
                row = '| ' + ds + ': [' + dc + '](' + url + ') | '

                for p in platforms:
                    if p in data_source_dict[ds]['platforms']:
                        row += ' X |'
                    else:
                        row += '   |'

                lines.append(row)

        return lines

    def _update_data(self, data, key, filename):
        """
        Update the json data on disk
        :param data: the MITRE ATT&CK data to update
        :param key: the json kv pair to update / where to store the data
        :param filename: filename of the file written to disk
        :return:
        """
        json_data = None
        with open(FILE_PATH_EDITOR_DATA + filename, 'r') as f:
            json_data = json.load(f)
            json_data[key] = data

        with open(FILE_PATH_EDITOR_DATA + filename, 'w') as f:
            json.dump(json_data, f, indent=2)

        # we also need this file in the CLI
        copyfile(FILE_PATH_EDITOR_DATA + filename, FILE_PATH_CLI_DATA + filename)

    def _dump_data(self, data, filename):
        """
        Write the json data to disk
        :param data: the MITRE ATT&CK data to save
        :param filename: filename of the file written to disk
        :return:
        """
        with open(FILE_PATH_EDITOR_DATA + filename, 'w') as f:
            json.dump(data, f, indent=2)

    def _write_to_wiki(self, text, filename):
        """
        Write the provided text to file to the Wiki
        :param text: the text in a list
        :param filename: filename of the file written to disk
        :return:
        """
        with open(FILE_PATH_WIKI + filename, 'w') as f:
            f.write('\n'.join(text))

    def _get_attack_id(self, technique, matrix):
        """
        Get the ATT&CK ID from the provided technique dict
        :param tech: a dictionary containing a single ATT&CK technique's STIX object
        :param matrix: ATT&CK Matrix
        :return: the technique ID or None if the technique is not matching the provided ATT&CK Matrix
        """
        for e in technique['external_references']:
            source_name = e.get('source_name', None)
            # return source_name
            if source_name == matrix:
                return e['external_id']
        return None

    def _get_techniques(self, cti_techniques, matrix):
        """
        Gets all techniques and applicable platforms for the provided ATT&CK Matrix and make a dict.
        :param matrix: ATT&CK Matrix
        :return: a list containing all techniques and applicable platforms
        """
        techniques = []
        for t in cti_techniques:
            id = self._get_attack_id(t, matrix)
            techniques.append({'technique_id': id,
                               'technique_name': t['name'],
                               'platforms': sorted(t['x_mitre_platforms']),
                               'autosuggest': id + ' - ' + t['name']})

        techniques = sorted(techniques, key=lambda t: t['technique_id'])
        return techniques

    def _get_data_components_platform_mapping_from_dict(self, data_source_dict):
        """
        Gets all the data components mapped to platforms in the following structure: {platform: [data source, data source]}
        :param data_source_dict: a dict with the data sources as created by the function _create_data_source_dict
        :return: a dictionary with the structure: {platform: [data source, data source]}
        """
        platforms = set()
        for k, v in data_source_dict.items():
            platforms.update(v['platforms'])

        ds_per_platform = {}
        for p in sorted(platforms):
            ds_per_platform[p] = []
            for k, v in data_source_dict.items():
                if p in v['platforms']:
                    ds_per_platform[p].extend(v['data_components'])

        return ds_per_platform

    def _get_data_sources_from_dict(self, data_source_dict):
        """
        Gets all the data components from the provided data source dict ({data source: {data_components: [], platforms: [], wiki_url: ...}})
        :param data_source_dict: a dict with the data sources as created by the function _create_data_source_dict
        :return: a sorted list with data data components
        """
        data_components = []
        for k, v in data_source_dict.items():
            data_components.extend(v['data_components'])

        return sorted(data_components)

    # this function is currently not used
    def _get_data_components_from_techniques(self, cti_techniques):
        """
        Gets all the data components from the provided techniques and make a set.
        :param cti_techniques: a dict with the CTI technique data
        :return: a sorted set with all data components
        """
        data_components = set()
        for t in cti_techniques:
            for ds in t.get('x_mitre_data_sources', []):
                ds = ds.split(':')[1][1:].lstrip().rstrip()
                data_components.add(ds)
        return sorted(data_components)

    def _create_data_source_dict(self, matrix):
        """
        Create a dictionary with only info on the data sources and components that we need
        :param matrix: ATT&CK Matrix
        :return: a dictionary with the structure: {data source: {data_components: [], platforms: [], wiki_url: ...}}
        """
        ds_dict = {}

        cti_data_sources = self._get_data_sources_from_cti(matrix)
        cti_data_sources = self.mitre.remove_revoked(cti_data_sources)
        cti_data_sources = self.mitre.remove_deprecated(cti_data_sources)

        cti_data_components = self._get_data_components_from_cti(matrix)
        cti_data_components = self.mitre.remove_revoked(cti_data_components)
        cti_data_components = self.mitre.remove_deprecated(cti_data_components)

        for ds in cti_data_sources:
            name = ds['name']
            if name not in ds_dict:
                ds_dict[name] = {}

            # add the platforms
            ds_dict[name]['platforms'] = ds.get('x_mitre_platforms', [])

            # add the ATT&CK Wiki URL
            url = ''
            for ex_ref in ds['external_references']:
                if ex_ref['source_name'] == matrix:
                    url = ex_ref['url']
                    break
            ds_dict[name]['wiki_url'] = url

            # add the data components
            ds_id = ds['id']
            for data_component in cti_data_components:
                if ds_id == data_component['x_mitre_data_source_ref']:  # we can match without the STIX relationship objects
                    if 'data_components' not in ds_dict[name]:
                        ds_dict[name]['data_components'] = []
                    ds_dict[name]['data_components'].append(data_component['name'])

        return ds_dict

    def _get_software(self, cti_techniques, matrix):
        """
        Get a list of dictionaries containing all software within ATT&CK
        :param cti_techniques: a dict with the CTI technique data
        :param matrix: ATT&CK Matrix
        :return: a list containing all software and applicable platforms
        """

        software = []
        all_platforms = self._get_platforms(cti_techniques)

        for s in self.attack_cti_software:
            platforms = set(s.get('x_mitre_platforms', list(all_platforms)))

            if len(all_platforms.intersection(platforms)) > 0:

                id = self._get_attack_id(s, matrix)
                if id:
                    software.append({'software_id': id,
                                    'software_name': s['name'],
                                     'platforms': sorted(list(platforms)),
                                     'autosuggest': id + ' - ' + s['name']})

        software = sorted(software, key=lambda s: s['software_id'])
        return software

    def _get_platforms(self, cti_techniques):
        """
        Retruns a set of all ATT&CK platforms
        :param cti_techniques: a dict with the CTI technique data
        :return: a set with all ATT&CK platforms
        """
        platforms = set()
        for t in cti_techniques:
            platforms.update(t.get('x_mitre_platforms', []))

        return platforms

    def _get_data_sources_from_cti(self, matrix):
        """
        Get all data source STIX objects from CTI for the provided ATT&CK Matrix
        :param matrix: ATT&CK Matrix
        :return: list of data source STIX objects
        """
        if matrix == MATRIX_ENTERPRISE:
            data_sources = self.mitre.TC_ENTERPRISE_SOURCE.query(Filter("type", "=", "x-mitre-data-source"))
        elif matrix == MATRIX_ICS:
            # ICS data sources are not yet in CTI, so this will not work
            data_sources = self.mitre.TC_ICS_SOURCE.query(Filter("type", "=", "x-mitre-data-source"))

        return data_sources

    def _get_data_components_from_cti(self, matrix):
        """
        Get all data component STIX objects from CTI for the provided ATT&CK Matrix
        :param matrix: ATT&CK Matrix
        :return: list of data component STIX objects
        """
        if matrix == MATRIX_ENTERPRISE:
            data_components = self.mitre.TC_ENTERPRISE_SOURCE.query(Filter("type", "=", "x-mitre-data-component"))
        elif matrix == MATRIX_ICS:
            # ICS data components are not yet in CTI, so this will not work
            data_components = self.mitre.TC_ICS_SOURCE.query(Filter("type", "=", "x-mitre-data-component"))

        return data_components


if __name__ == "__main__":
    attack_data = ATTACKData()
    attack_data.execute_refresh_json_data()
    attack_data.execute_refresh_wiki()