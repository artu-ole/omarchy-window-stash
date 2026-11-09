"""Recognize only integration code emitted by earlier Window Stash installers."""
import re

import shortcuts

BEGIN = "-- Window Stash: begin"
END = "-- Window Stash: end"
LITERAL = r'''(?:"(?:\\.|[^"\\])*"|'(?:\\.|[^'\\])*')'''


def lua_literal(value):
    """Read generated short Lua strings without executing configuration code."""
    result = bytearray()
    escapes = dict(zip('abfnrtv', ('\a', '\b', '\f', '\n', '\r', '\t', '\v')))
    index = 1
    while index < len(value)-1:
        character = value[index]
        index += 1
        if character != '\\':
            result.extend(character.encode('utf-8'))
            continue
        character = value[index]
        index += 1
        if '0' <= character <= '9':
            digits = character
            while index < len(value)-1 and len(digits) < 3 and '0' <= value[index] <= '9':
                digits += value[index]
                index += 1
            number = int(digits)
            if number > 255:
                raise ValueError('Invalid Lua string escape')
            result.append(number)
        elif character in ('\\', '"', "'"):
            result.extend(character.encode('utf-8'))
        elif character in escapes:
            result.extend(escapes[character].encode('utf-8'))
        else:
            raise ValueError('Unsupported Lua string escape')
    return result.decode('utf-8')


def binding_block(text, binary, target):
    """Accept only our loader or known literal legacy calls inside one block."""
    begins, ends, offset = [], [], 0
    for line in text.splitlines(keepends=True):
        if line.strip() == BEGIN:
            begins.append((offset, offset+len(line), line))
        elif line.strip() == END:
            ends.append((offset, offset+len(line), line))
        offset += len(line)
    if not begins and not ends:
        return None
    if len(begins) != 1 or len(ends) != 1 or begins[0][1] > ends[0][0]:
        raise RuntimeError('Malformed or repeated Window Stash shortcut markers; no configuration changed')
    begin, end = begins[0], ends[0]
    lines, comments, pending_comments = [], {}, []
    for line in text[begin[1]:end[0]].splitlines():
        line=line.strip()
        if not line:
            continue
        if line.startswith('--') and not line.startswith('--['):
            pending_comments.append(line)
            continue
        comments[len(lines)]=pending_comments
        pending_comments=[]
        lines.append(line)
    imported = {key: '' for key in shortcuts.DEFAULT_SHORTCUTS}
    calls, overrides, loader = [], [], None
    try:
        for position,line in enumerate(lines):
            unbind = re.fullmatch(r'hl\.unbind\s*\(\s*('+LITERAL+r')\s*\)\s*;?', line)
            if unbind:
                chord=shortcuts.normalize(lua_literal(unbind[1]))
                if not chord or any(override['chord']==chord for override in overrides):
                    raise ValueError('Empty or repeated legacy override')
                overrides.append(dict(chord=chord,line=line,comments=comments[position],position=position))
                continue
            candidate = re.fullmatch(r'dofile\s*\(\s*('+LITERAL+r')\s*\)\s*;?', line)
            if candidate:
                if loader is not None or lua_literal(candidate[1]) != str(target/'controller/shortcuts.lua'):
                    raise ValueError('Unknown shortcut loader')
                loader=position
                continue
            match = re.fullmatch(r'o\.bind\s*\(\s*('+LITERAL+r')\s*,\s*('+LITERAL+r')\s*,\s*('+LITERAL+r')\s*\)\s*;?', line)
            if not match:
                raise ValueError('Unknown shortcut code')
            chord, description, command = (lua_literal(part) for part in match.groups())
            key = next((key for key, (action, label) in shortcuts.ACTIONS.items()
                        if description == label and command == str(binary)+' '+action), None)
            if key is None or any(call['setting'] == key for call in calls):
                raise ValueError('Unknown or repeated shortcut action')
            chord = shortcuts.normalize(chord)
            imported[key] = chord
            calls.append(dict(setting=key, chord=chord, description=description, command=command,position=position))
        if loader is not None:
            if calls or loader != len(lines)-1:
                raise ValueError('Mixed or misplaced shortcut loader')
            imported={}
        elif any(not any(call['chord']==override['chord'] and call['position']>override['position'] for call in calls)
                 for override in overrides):
            raise ValueError('Legacy override is not paired with its following owned binding')
    except (ValueError, UnicodeError) as error:
        raise RuntimeError('Unrecognized custom code inside the Window Stash shortcut block; '
                           'move that code outside its markers before updating or removing the plugin') from error
    return dict(start=begin[0], end=end[1], beginLine=begin[2], endLine=end[2], legacy=imported, calls=calls,overrides=overrides)


def integration_patches():
    return {
        "Switcher.qml": [
            ('  property var pendingActivation: null', '  property var pendingActivation: null\n  // Window Stash integration\n  property string pendingStashAddress: ""'),
            ('    pendingActivation = originalToplevel\n', '    pendingStashAddress = ""\n    pendingActivation = originalToplevel\n'),
            ('    pendingActivation = selected.toplevel\n', '    pendingStashAddress = selected.stashManaged ? selected.address : ""\n    pendingActivation = selected.toplevel\n'),
            ('    pendingActivation = record.toplevel\n', '    pendingStashAddress = record.stashManaged ? record.address : ""\n    pendingActivation = record.toplevel\n'),
            ('      var target = root.pendingActivation\n', '      var target = root.pendingActivation\n      var stashAddress = root.pendingStashAddress\n      root.pendingStashAddress = ""\n'),
            ('        if (serial === root.openSerial && !root.opened && target) target.activate()',
             '''        if (serial === root.openSerial && !root.opened && target) {
          if (stashAddress) {
            var address = stashAddress.indexOf("0x") === 0 ? stashAddress : "0x" + stashAddress
            Quickshell.execDetached([Quickshell.env("HOME") + "/.local/bin/window-stash", "activate", address])
          } else target.activate()
        }'''),
        ],
        "components/WindowRecords.qml": [
            ('      minimized: toplevel && toplevel.minimized === true',
             '''      // The controller decides ownership; IPC tag snapshots may lag.
      stashManaged: workspaceName === "special:window-stash",
      minimized: toplevel && toplevel.minimized === true''')
        ],
        "model/WindowSnapshot.js": [
            ('  "minimized"', '  "minimized",\n  "stashManaged"')
        ]
    }


