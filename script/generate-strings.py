#! /usr/bin/env python3
import argparse
import builtins
import jinja2
import os
import re
import subprocess

# check if selector a is "better" than selector b
def selector_is_better(a, b):
    # prefer selector that start with theese prefixes
    highprio_prefixes = [
        'kAudioObject',
        'kAudioDevice',
        'kAudioStream',
        'kAudioControl',
        'kAudioLevelControl',
        'kAudioPlugIn',
        ]

    a_is_highprio = any([a.startswith(prefix) for prefix in highprio_prefixes])
    b_is_highprio = any([b.startswith(prefix) for prefix in highprio_prefixes])

    if a_is_highprio == b_is_highprio:
        # prefer shorter selectors since they're likely more generic
        # (like e.g. AudioDevice vs AudioClockDevice)
        return len(a) < len(b)

    return a_is_highprio

parser = argparse.ArgumentParser()
parser.add_argument('-c', type=str, help='compiler executable', default='clang')
parser.add_argument('-s', type=str, help='sysroot path')
parser.add_argument('-o', type=str, help='output c++ file', required=True)

args = parser.parse_args()

input_file='CoreAudio/AudioServerPlugIn.h'

compiler_input='''
#include <%s>
''' % input_file

compiler_command = [
    args.c,
    '-isysroot', args.s,
    '-',
    '-E', '-',
]

# run preprocessor on given header and capture its output
p = subprocess.run(compiler_command,
    stdout=subprocess.PIPE,
    input=compiler_input,
    encoding='utf-8',
    check=True)

# preprocessor output, contains all definitions we're interested in
defs = p.stdout

selector2code = {}
code2selector = {}
class2code = {}
scope2code = {}
operation2code = {}
error2code = {}
formatID = set()
formatFlag = set()

# fill selector2code
for m in re.finditer(r'(kAudio\S+Property\S+)\s*=\s*(\'\S+\')', defs):
    name, code = m.group(1), m.group(2)

    # skip scopes
    if name.startswith('kAudioObjectPropertyScope'):
        continue

    # skip elements
    if name.startswith('kAudioObjectPropertyElement'):
        continue

    # skip error codes
    if name.startswith('kAudioHardware'):
        continue

    # skip custom property types
    if name.startswith('kAudioServerPlugInCustomPropertyDataType'):
        continue

    # on duplicate code, choose "better" selector
    if code in code2selector:
        other_name = code2selector[code]
        if selector_is_better(name, other_name):
            del selector2code[other_name]
        else:
            continue

    selector2code[name] = code
    code2selector[code] = name

# fill class2code
for m in re.finditer(r'(kAudio\S+ClassID)\s*=\s*(\'\S+\')', defs):
    name, code = m.group(1), m.group(2)
    class2code[name] = code

# fill scope2code
for m in re.finditer(r'(kAudioObjectPropertyScope\S+)\s*=\s*(\'\S+\')', defs):
    name, code = m.group(1), m.group(2)
    scope2code[name] = code

# fill operation2code
for m in re.finditer(r'(kAudioServerPlugInIOOperation\S+)\s*=\s*(\'\S+\')', defs):
    name, code = m.group(1), m.group(2)
    operation2code[name] = code

# fill error2code
for m in re.finditer(r'(kAudioHardware\S+)\s*=\s*(\'\S+\')', defs):
    name, code = m.group(1), m.group(2)
    error2code[name] = code

# fill formatID and formatFlag
for m in re.finditer(r'(kAudioFormat\S+)\s*=\s*(\S+)', defs):
    name, code = m.group(1), m.group(2)
    if name.startswith('kAudioFormatFlag'):
        if code != '0':
            formatFlag.add(name)
    else:
        formatID.add(name)

env = jinja2.Environment(
    trim_blocks=True,
    lstrip_blocks=True,
    undefined = jinja2.StrictUndefined)

template = env.from_string('''
// THIS FILE IS AUTO-GENERATED. DO NOT EDIT!

// Generator: {{ generator_script }}
// Source: {{ generator_input }}

// Copyright (c) libASPL authors
// Licensed under MIT

#include "Strings.hpp"

namespace aspl {

std::string ClassIDToString(AudioClassID classID)
{
    switch (classID) {
    {% for name in sorted(class2code.keys()) %}
    case {{ name }}:
        return "{{ name }}";
    {% endfor %}
    default:
        return CodeToString(classID);
    }
}

std::string PropertySelectorToString(AudioObjectPropertySelector selector)
{
    switch (selector) {
    {% for name in sorted(selector2code.keys()) %}
    case {{ name }}:
        return "{{ name }}";
    {% endfor %}
    default:
        return CodeToString(selector);
    }
}

std::string PropertyScopeToString(AudioObjectPropertyScope scope)
{
    switch (scope) {
    {% for name in sorted(scope2code.keys()) %}
    case {{ name }}:
        return "{{ name }}";
    {% endfor %}
    default:
        return CodeToString(scope);
    }
}

std::string OperationIDToString(UInt32 operationID)
{
    switch (operationID) {
    {% for name in sorted(operation2code.keys()) %}
    case {{ name }}:
        return "{{ name }}";
    {% endfor %}
    default:
        return CodeToString(operationID);
    }
}

std::string StatusToString(OSStatus status)
{
    switch (status) {
    case kAudioHardwareNoError:
        return "OK";
    {% for name in sorted(error2code.keys()) %}
    case {{ name }}:
        return "{{ name }}";
    {% endfor %}
    default:
        return CodeToString(UInt32(status));
    }
}

std::string FormatIDToString(AudioFormatID formatID)
{
    switch (formatID) {
    {% for name in sorted(formatID) %}
    case {{ name }}:
        return "{{ name }}";
    {% endfor %}
    default:
        return CodeToString(formatID);
    }
}

std::string FormatFlagsToString(AudioFormatFlags formatFlags)
{
    std::string ret;
    {% for name in sorted(formatFlag) %}
    if (formatFlags & {{ name }}) {
        if (!ret.empty()) {
            ret += "|";
        }
        ret += "{{ name }}";
    }
    {% endfor %}
    return ret;
}

} // namespace aspl
'''.strip())

text = template.render(
    **builtins.__dict__,
    selector2code=selector2code,
    class2code=class2code,
    scope2code=scope2code,
    operation2code=operation2code,
    error2code=error2code,
    formatID=formatID,
    formatFlag=formatFlag,
    generator_script=os.path.basename(__file__),
    generator_input=input_file,
    )

with open(args.o, 'w') as out:
    print(text, file=out)
