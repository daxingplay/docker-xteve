#!/usr/bin/env python3
import click
import requests
import re

from lxml import etree
from datetime import datetime, timedelta, time

def valid_xml_char_ordinal(c):
    """
    Determine whether the given character is valid for xml.
    """
    codepoint = ord(c)
    return (
        0x20 <= codepoint <= 0xD7FF or
        codepoint in (0x9, 0xA, 0xD) or
        0xE000 <= codepoint <= 0xFFFD or
        0x10000 <= codepoint <= 0x10FFFF
        )

def unescape(text):
    """
    Safe check of the existence of the unescape function as the future module
    doesn't appear to have it yet.

    https://github.com/PythonCharmers/python-future/issues/247
    """
    try:
        import html
        return ''.join(c for c in html.unescape(text) if valid_xml_char_ordinal(c))
    except:
        return text


def getAPIRoot(username, password, host, port):
    """
    Simple function to form the url of the OpenWebif server.
    More info at:
    
    https://github.com/E2OpenPlugins/e2openplugin-OpenWebif/wiki/OpenWebif-API-documentation
    """
    if username:
        url = 'http://{}:{}@{}:{}'.format(
                username, password, host, port)
    else:
        url = 'http://{}:{}'.format(host, port)
    return url


def getBouquets(bouquet, api_root_url, list_bouquets):
    """
    Function to get the list of bouquets from the OpenWebif API
    
    return_type: dict
    return_model:
        {
            "bouquet_name_1": "sRef_1",
            ...
            "bouquet_name_n": "sRef_n",
        }
    """
    result = {}
    url = '{}/api/bouquets'.format(api_root_url)
    try:
        bouquets_data = requests.get(url)
        bouquets = bouquets_data.json()['bouquets']
        for b in bouquets:
            if list_bouquets:
                print(u"Found bouquet: {}".format(b[1]))
            if b[1] == bouquet or not bouquet:
                result[b[1]] = b[0]
    except Exception:
        raise
    return result


def getBouquetsServices(bouquets, api_root_url):
    """
    Function to return the list of services (channels) for each bouquet in the
    bouquets param

    params:
        - boutquets: [bouquet_obj_1, bouquet_obj_2, ...]
        - api_root_url: Root URL of the OpenWebif server
    returns:
        - type: dict
        - model:
            {
                "bouquet_name_1": [svc_1_obj, svc_2_obj, ..., svc_n_obj],
                ...
                "bouquet_name_n": [svc_1_obj, svc_2_obj, ..., svc_n_obj]
            }
    """
    services = {}
    try:
        for bouquet_name, bouquet_svc_ref in bouquets.items():
            url = '{}/api/getservices?sRef={}'.format(api_root_url, bouquet_svc_ref)
            services_data = requests.get(url)
            services[bouquet_name] = services_data.json()['services']
    except Exception:
        raise
    return services


def getEPGs(bouquets_services, api_root_url):
    """
    Function to get the EPGs for the services in the bouquet_services param.

    params:
        - bouquet_services: [svc_obj_1, svc_obj_2, ...]
        - api_root_url: Root URL of the OpenWebif server
    returns:
        - type: dict
        - model:
            {
                "program_id": [ event_obj_1, event_obj_2, ...],
                ...,
                "program_id": [ event_obj_1, event_obj_2, ...]
            }
    """
    epg = {}
    for _, services in bouquets_services.items():
        for service in services:
            if service['pos']:
                url = u'{}/api/epgservice?sRef={}'.format(api_root_url, service['servicereference'])
                debug_message = u"Getting EPG for Service {}.{} ({}) from {}".format(
                    service['pos'], service['servicename'], service['program'],
                    url)
                print(debug_message.encode('utf-8'))
                try:
                    service_epg_data = requests.get(url)
                    epg[service['program']] = service_epg_data.json()['events']
                except Exception:
                    raise
    return epg


def getOffset(api_root_url):
    now = datetime.timestamp(datetime.now())
    offset = (datetime.fromtimestamp(now) - datetime.utcfromtimestamp(now)).total_seconds()
    hours = round(offset / 3600)
    minutes = (offset - (hours * 3600))
    tzo = "{:+05}".format(int(hours * 100 + (round(minutes / 900) * 900 / 60)))

    print("Setting TZ Offset from UTC to {}".format(tzo))
    return tzo


def addChannels2XML(xmltv, bouquets_services, epg, api_root_url):
    """
    Function to add the list of services/channels to the resultant XML object.

    returns:
        - type: lxml.etree
    """
    for _, services in bouquets_services.items():
        for service in services:
            if service['pos']:
                channel = etree.SubElement(xmltv, 'channel')
                channel.attrib['id'] = '{}'.format(service['program'])
                etree.SubElement(channel, 'display-name').text = unescape(service['servicename'])
                etree.SubElement(channel, 'display-name').text = str(service['pos'])
                if epg[service['program']]:
                    first_event = epg[service['program']][0]
                    channel_picon = etree.SubElement(channel, 'icon')
                    channel_picon.attrib['src'] = '{}{}'.format(api_root_url, first_event['picon'])
    return xmltv


def addCategories2Programme(programme, event):
    """
    Function to add the catergories to a program. Returns the XML program object
    with the cateogry added.

    returns:
        - type: lxml.etree
    """
    categories = re.search(r'^\[(?P<C1>[\w\s]+)[\.\s]*(?P<C2>[\w\s]+)*\]', event['shortdesc'])
    if categories:
        for category in categories.groupdict().values(): 
            if category:
                programme_category = etree.SubElement(programme, 'category')
                programme_category.attrib['lang'] = 'en'
                programme_category.text = '{}'.format(category)

    return programme

def parseSEP(text):
    S = ''
    E = ''
    P = ''
    is_a_match = True
    match = None

    c4_style = re.search(r'(?:S(?P<S>\d+)(?:\/|\s)*)?(?:Ep|E)\s*(?P<E>\d+)(?:\/(?P<P>\d+))?', text)
    bbc_style = re.search(r'^(?P<E>\d+)\/(?P<P>\d+)\.', text)
    if c4_style:
        match = c4_style
    elif bbc_style:
        match = bbc_style
    else:
        is_a_match = False

    if match:
        group_names = match.groupdict().keys()
        if 'S' in group_names:
            S = '{}'.format(int(match.group('S')) - 1 if match.group('S') else '')
        if 'E' in group_names:
            E = '{}'.format(int(match.group('E')) - 1 if match.group('E') else '')
        if 'P' in group_names:
            P = '{}'.format(int(match.group('P')) - 1 if match.group('P') else '')
        
    return is_a_match, '{}.{}.{}'.format(S, E, P)


def addSeriesInfo2Programme(programme, event):
    """
    Function to add Information to programs with the Categories Series or Show
    relating to the episode number or original air date.

    returns:
        - type: lxml.etree
    """
    original_air_date = re.search( r'(\d{2})[\/|\.|\-](\d{2})[\/|\.|\-](\d{4})', event['shortdesc'])
    match_epnum, epnum = parseSEP(event['shortdesc'])

    # Don't attempt to put an episode-num to certain categories
    try:
        existing_category = programme.find('category')
        if existing_category.text in ('Movie', 'News'):
            return programme
    except AttributeError:
        pass

    if match_epnum:
        programme_epnum = etree.SubElement(programme, 'episode-num')
        programme_epnum.attrib['system'] = 'xmltv_ns'
        programme_epnum.text = epnum

        # If it hasn't got a category but a epnum then it must be a Series
        if existing_category is None:
            programme_category = etree.SubElement(programme, 'category')
            programme_category.attrib['lang'] = 'en'
            programme_category.text = 'Series'

    if original_air_date:
        programme_epnum = etree.SubElement(programme, 'episode-num')
        programme_epnum.attrib['system'] = 'original-air-date'
        programme_epnum.text = "{}-{}-{}".format(
            original_air_date.group(3),
            original_air_date.group(2),
            original_air_date.group(1))
    # else:
    #     original_air_date = re.search( r'(\d\d).(\d\d).(\d\d\d\d)', event['date'])
    #     programme_epnum = etree.SubElement(programme, 'episode-num')
    #     programme_epnum.attrib['system'] = 'original-air-date'
    #     programme_epnum.text = "{}-{}-{}".format(
    #         original_air_date.group(3),
    #         original_air_date.group(2),
    #         original_air_date.group(1))

    return programme


def addMovieCredits(programme, event):
    try:
        existing_category = programme.find('category')
        if existing_category.text in ('Movie'):
            cast = event['longdesc'].split('\n', 2)
            if len(cast)>2:
                credits = etree.SubElement(programme, 'credits')
                director = etree.SubElement(credits, 'director')
                director.text = cast[1]
                for cast in cast[2][:-1].split('\n'):
                    actor = etree.SubElement(credits, 'actor')
                    actor.text = cast
    except AttributeError:
        pass
    return programme


def addEvents2XML(xmltv, epg, tzoffset):
    """
    Function to add events (programms) to the XMLTV structure.

    returns:
        - type: lxml.etree
    """
    for service_program, events in epg.items():
        for event in events:
            # Time Calculations and transformations
            start_dt = datetime.fromtimestamp(event['begin_timestamp'])
            start_dt_str = start_dt.strftime("%Y%m%d%H%M%S {}".format(tzoffset))
            end_dt = start_dt + timedelta(minutes=event['duration'])
            end_dt_str = end_dt.strftime("%Y%m%d%H%M%S {}".format(tzoffset))

            programme = etree.SubElement(xmltv, 'programme')
            programme.attrib['channel'] = str(service_program)
            programme.attrib['start'] = start_dt_str
            programme.attrib['stop'] = end_dt_str

            programme_duration = etree.SubElement(programme, 'length')
            programme_duration.attrib['units'] = 'minutes'
            programme_duration.text = str(event['duration'])

            programme_desc = etree.SubElement(programme, 'desc')
            if event['longdesc'] == '':
                programme_desc.text = unescape(event['shortdesc'])
            else:
                programme_desc.text = unescape(event['longdesc'])
                subtitle_first_step = re.sub(r'^(\[.+\]\s*)', '', event['shortdesc'])
                subtitle = re.sub(r'\s*\([SE]\d+.*\)', '', subtitle_first_step)
                if len(subtitle) > 0:
                    programme_subtitle = etree.SubElement(programme, 'sub-title')
                    programme_subtitle.text = unescape(subtitle)
                    programme_subtitle.attrib['lang'] = 'en'
            programme_desc.attrib['lang'] = 'en'

            title = unescape(event['title'])
            if 'New: ' in title:
                _ = etree.SubElement(programme, 'new')
                title = title.replace('New: ', '')
            programme_title = etree.SubElement(programme, 'title')
            programme_title.text = title 
            programme_title.attrib['lang'] = 'en'

            programme = addCategories2Programme(programme, event)
            programme = addSeriesInfo2Programme(programme, event)   
            programme = addMovieCredits(programme, event)         

    return xmltv


def generateXMLTV(bouquets_services, epg, api_root_url, tzoffset):
    """
    Function to generate the XMLTV object

    returns:
        - type: string
        - desc: Representation of the XMLTV object as a String.
    """
    print(u"Generating XMLTV payload.")
    xmltv = etree.Element('tv')
    xmltv.attrib['generator-info-url'] = 'https://github.com/cvarelaruiz'
    xmltv.attrib['generator-info-name'] = 'OpenWebIf 2 Plex XMLTV'
    xmltv.attrib['date'] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    xmltv = addChannels2XML(xmltv, bouquets_services, epg, api_root_url)
    xmltv = addEvents2XML(xmltv, epg, tzoffset)

    return etree.tostring(xmltv, pretty_print=True)


@click.command()
@click.option('-b', '--bouquet', help='The name of the bouquet to parse. If not'
              ' specified parse all bouquets.', type=click.STRING)
@click.option('-u', '--username', help='OpenWebIf Username', type=click.STRING)
@click.option('-p', '--password', help='OpenWebIf Password', type=click.STRING)
@click.option('-h', '--host', help='OpenWebIf Host', default='localhost',
    type=click.STRING)
@click.option('-P', '--port', help='OpenWebIf Port', default=80, type=click.INT)
@click.option('-o', '--output-file', help='Output file', default='epg.xml',
    type=click.STRING)
@click.option('-l', '--list-bouquets', help='Display a list of bouquets.', 
    is_flag=True)
@click.option('-V', '--version', help='displays the version of the package.',
    is_flag=True)
def main(bouquet=None, username=None, password=None, host='localhost', port=80,
    output_file='epg.xmltv', list_bouquets=False, version=False):

    if version:
        print("OWI2PLEX version 0.1-alpha-3")
        exit(0)

    api_root_url = getAPIRoot(username=username, password=password, host=host, port=port)
    bouquets = getBouquets(bouquet=bouquet, api_root_url=api_root_url,
        list_bouquets=list_bouquets)
    bouquets_services = getBouquetsServices(bouquets=bouquets, api_root_url=api_root_url)
    epg = getEPGs(bouquets_services=bouquets_services, api_root_url=api_root_url)
    tzoffset = getOffset(api_root_url=api_root_url)
    xmltv = generateXMLTV(bouquets_services, epg, api_root_url, tzoffset)
    print(u"Saving XMLTV payload to file {}".format(output_file))
    try:
        with open(output_file, 'w') as xmltv_file:
            xmltv_file.write(xmltv.decode("utf-8"))
            print(u"Boom!")
    except Exception:
        print(u"Uh-oh!")
        raise

if __name__ == '__main__':
    main()