#!/usr/bin/python3

import re
import base64
import urllib.request
import yaml
from html.parser import HTMLParser
from collections import OrderedDict
from yaml.resolver import BaseResolver
from git import cmd
import json
import argparse
import time

def dict_representer(dumper, data):
    return dumper.represent_dict(data.items())


def dict_constructor(loader, node):
    return OrderedDict(loader.construct_pairs(node))


yaml.add_representer(OrderedDict, dict_representer)
yaml.add_constructor(BaseResolver.DEFAULT_MAPPING_TAG, dict_constructor)


class AndroidImagesParser(HTMLParser):
    def __init__(self, config):
        HTMLParser.__init__(self)
        self.config = config
        self.devices = self.config['devices'].keys()
        self.version = self.config['version']
        self.version_open = False
        self.hash_pattern = re.compile(r'\b[0-9a-f]{64}\b')
        self.type = "factory"
        self.images = {}
        self.build = False
        self.device = False

    def handle_starttag(self, tag, attrs):
        if tag == 'meta' and len(attrs) > 1 and attrs[0][1] == "og:url":
            suffix = attrs[1][1].split('/').pop()
            if suffix == "images": self.type = "factory"
            if suffix == "ota": self.type = "ota"
        if tag == 'tr':
            for attr in attrs:
                if attr[0] == 'id':
                    for device in self.devices:
                        if attr[1].startswith(device):
                            self.device = device

    def handle_data(self, data):
        if self.device:
            data = data.strip()
            if "https://dl.google.com/" in self._HTMLParser__starttag_text and self.version_open == True:
                self.images.setdefault(
                    self.device, {}
                )["%s_url" % self.type] = self._HTMLParser__starttag_text.split('"')[1]
            if "https://flash.android.com" in self._HTMLParser__starttag_text and self.version_open == True and self.type == "factory":
                self.images.setdefault(
                    self.device, {}
                )["flash_url"] = self._HTMLParser__starttag_text.split('"')[1]
            if len(data) > 6:
                if self.hash_pattern.match(data) and self.version_open == True:
                    self.images.setdefault(
                        self.device, {}
                    )["%s_sha256" % self.type] = data
                elif data.split(' ')[0].startswith("%s." % self.version):
                    _re = re.search(r'\b\w{3} \d{4}(?P<optional_close_bracket>\)?)', data)
                    if (_re and _re.group('optional_close_bracket') != '') or (re and "All carriers except" in data):
                        self.version_open = True
                        tokens = data.split(" ")
                        self.images.setdefault(
                            self.device, {}
                        )['build_id'] = tokens[1].replace("(", "").replace(",", "")

    def handle_endtag(self, tag):
        if tag == 'tr' and self.device:
            if self.version_open == True:
                self.version_open = False
            self.device = False
            self.build = False

def get_all_aosp_tags(tag_filter):
    all_tags = []
    platform_build_url = "https://android.googlesource.com/platform/build"
    for line in cmd.Git().ls_remote("--sort=v:refname", platform_build_url, tags=True, refs=True).split('\n'):
        try:
            (ref, tag) = line.split('\t')
        except ValueError:
            pass
        if tag_filter in tag:
            all_tags.append(tag.replace("refs/tags/", ""))
    return all_tags

def get_build_id_to_aosp_tag_mapping(aosp_tags):
    mapping = {}
    platform_build_git_url = "https://android.googlesource.com/platform/build/+/refs/tags/{}/core/build_id.mk?format=TEXT"
    build_id_filter = "BUILD_ID="
    for aosp_tag in aosp_tags:
        output = base64.decodebytes(urllib.request.urlopen(platform_build_git_url.format(aosp_tag)).read()).decode()
        for line in output.split('\n'):
            if build_id_filter in line:
                build_id = re.search(build_id_regex, line)[0]
                mapping[build_id] = aosp_tag
    return mapping

default_android_version = "12.0"
config_file = "config.json"
all_devices = [
    "walleye", "taimen",
    "blueline", "crosshatch",
    "sargo", "bonito",
    "flame", "coral",
    "sunfish",
    "redfin", "bramble", "barbet"
]
image_url = "https://developers.google.com/android/images"
ota_url = "https://developers.google.com/android/ota"
accept_tos_header = {'Cookie': 'devsite_wall_acks=nexus-image-tos,nexus-ota-tos'}
build_id_regex = '([A-Z0-9]{4,5}\.[0-9]{6}\.[0-9]{3})'

if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument('-v', '--version', default=default_android_version, help='android version', type=str)
    parser.add_argument('-d', '--devices', default=",".join(all_devices), help='devices to update', type=str)
    args = parser.parse_args()
    devices = [d for d in args.devices.split(',')]

    config = {
        'version': args.version,
        'datetime': int(time.time()),
        'devices': {d:{} for d in devices}
    }
    all_aosp_tags = get_all_aosp_tags("android-{}".format(config['version']))
    build_id_aosp_tag_mapping = get_build_id_to_aosp_tag_mapping(all_aosp_tags)

    parser = AndroidImagesParser(config)
    parser.feed(str(urllib.request.urlopen(urllib.request.Request(image_url, headers=accept_tos_header)).read()))
    parser.feed(str(urllib.request.urlopen(urllib.request.Request(ota_url, headers=accept_tos_header)).read()))

    for device in devices:
        for values in parser.images[device].items():
            config['devices'].setdefault(device, {})[values[0]] = values[1]
            if values[0] == "build_id":
                build_id = re.search(build_id_regex, values[1])[0]
                if build_id in build_id_aosp_tag_mapping:
                    config['devices'].setdefault(device, {})['aosp_tag'] = build_id_aosp_tag_mapping[build_id]
                else:
                    print("Unable to find AOSP tag for build_id {} for device {}".format(build_id, device))
                    exit(1)

    json_output = json.dumps(config, indent=2)
    print(json_output)

    with open(config_file, "w") as outfile:
        outfile.writelines(json_output)

    print("updated file {}".format(config_file))
