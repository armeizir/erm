"""Small shared HTML vocabulary for the SMT editor, read-only view and PDF."""
import re
from html import escape
from html.parser import HTMLParser

RICH_FIELDS = ('tujuan', 'ruang_lingkup', 'referensi', 'tanggung_jawab',
               'langkah_kerja', 'catatan_revisi')
TAGS = {'p', 'div', 'br', 'strong', 'b', 'em', 'i', 'u', 'ul', 'ol', 'li',
        'h3', 'h4', 'blockquote'}
BLOCKS = {'p', 'div', 'h3', 'h4', 'blockquote', 'ul', 'ol', 'li'}
RICH_PATTERN = re.compile(r'</?(?:' + '|'.join(sorted(TAGS)) + r')(?:\s[^>]*|\s*)>', re.I)


class Node:
    def __init__(self, tag='', attrs=None):
        self.tag = tag
        self.attrs = attrs or {}
        self.children = []


class _Parser(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.root = Node()
        self.stack = [self.root]
        self.suppressed = 0

    def handle_starttag(self, tag, attrs):
        if tag in {'script', 'style', 'iframe', 'object', 'svg', 'math', 'template'}:
            self.suppressed += 1
            return
        if self.suppressed or tag not in TAGS:
            return
        clean = {}
        for key, value in attrs:
            if key == 'style':
                declarations = []
                for part in (value or '').lower().split(';'):
                    prop, _, val = part.partition(':')
                    prop, val = prop.strip(), val.strip()
                    if prop == 'text-align' and val in {'left', 'center', 'right', 'justify'}:
                        declarations.append(f'text-align:{val}')
                    if prop == 'margin-left' and re.fullmatch(r'\d{1,3}px', val):
                        declarations.append(f'margin-left:{min(int(val[:-2]), 160)}px')
                if declarations:
                    clean['style'] = ';'.join(declarations)
            if key == 'start' and tag == 'ol' and re.fullmatch(r'\d{1,4}', value or ''):
                clean['start'] = str(max(1, int(value)))
        # SMT_SUBSECTION_V1: bounded numeric section; no arbitrary CSS/HTML attributes.
        for key, value in attrs:
            if key == 'data-section' and tag == 'ol' and re.fullmatch(r'[1-9][0-9]?', value or ''):
                clean['data-section'] = value
        node = Node(tag, clean)
        self.stack[-1].children.append(node)
        if tag != 'br':
            self.stack.append(node)

    def handle_startendtag(self, tag, attrs):
        self.handle_starttag(tag, attrs)
        if tag != 'br':
            self.handle_endtag(tag)

    def handle_endtag(self, tag):
        if tag in {'script', 'style', 'iframe', 'object', 'svg', 'math', 'template'}:
            self.suppressed = max(0, self.suppressed - 1)
            return
        if self.suppressed:
            return
        for index in range(len(self.stack)-1, 0, -1):
            if self.stack[index].tag == tag:
                self.stack = self.stack[:index]
                break

    def handle_data(self, data):
        if not self.suppressed:
            self.stack[-1].children.append(data)


def parse_html(value):
    parser = _Parser()
    parser.feed(value)
    parser.close()
    return parser.root


def _serialize(node):
    if isinstance(node, str):
        return escape(node)
    body = ''.join(_serialize(child) for child in node.children)
    if not node.tag:
        return body
    attrs = ''.join(f' {key}="{escape(value, quote=True)}"' for key, value in node.attrs.items())
    return f'<{node.tag}{attrs}>' + ('' if node.tag == 'br' else body + f'</{node.tag}>')


def _manual_subsections(root):
    """Recognize consecutive manual subsection lines for display; no DB writes."""
    pattern = re.compile(r'^\s*([1-9][0-9]?)\.([1-9][0-9]{0,3})\.?\s+')
    def visible(node):
        return node if isinstance(node, str) else ''.join(visible(c) for c in node.children)
    def remove_prefix(node, count):
        for index, child in enumerate(node.children):
            if not count: break
            if isinstance(child, str):
                take = min(count, len(child))
                node.children[index] = child[take:]
                count -= take
            else:
                count = remove_prefix(child, count)
        return count
    # Only paragraphs containing inline formatting are candidates. Existing lists
    # and headings retain their original structure and numbering.
    expanded = []
    for node in root.children:
        if isinstance(node, Node) and node.tag in {'p', 'div'} and not any(
            isinstance(c, Node) and c.tag in BLOCKS for c in node.children
        ):
            pieces = re.split(r'<br\s*/?>|\r?\n', ''.join(_serialize(c) for c in node.children))
            for piece in pieces:
                part = Node('p', dict(node.attrs))
                part.children = parse_html(piece).children
                expanded.append(part)
        else:
            expanded.append(node)
    result = []; index = 0; converted = False
    while index < len(expanded):
        node = expanded[index]
        first = pattern.match(visible(node)) if isinstance(node, Node) and node.tag == 'p' else None
        if not first:
            result.append(node); index += 1; continue
        group = []; cursor = index; expected = int(first[2])
        while cursor < len(expanded):
            part = expanded[cursor]
            match = pattern.match(visible(part)) if isinstance(part, Node) and part.tag == 'p' else None
            if not match or match[1] != first[1] or int(match[2]) != expected: break
            group.append((part, match.end())); expected += 1; cursor += 1
        if len(group) < 2:
            result.append(node); index += 1; continue
        converted = True
        listing = Node('ol', {'start': first[2], 'data-section': first[1]})
        for part, length in group:
            remove_prefix(part, length)
            item = Node('li', dict(part.attrs)); item.children = part.children
            listing.children.append(item)
        result.append(listing); index = cursor
    if converted: root.children = result
    return root


def editor_html(value):
    """Legacy plain text stays literal, including angle brackets and line breaks."""
    value = str(value or '')
    if not RICH_PATTERN.search(value):
        return _serialize(_manual_subsections(parse_html('<p>' + escape(value).replace('\n', '<br>') + '</p>'))) if value else ''
    return _serialize(_manual_subsections(parse_html(value)))


def clean_value(value):
    value = str(value or '')
    return editor_html(value) if RICH_PATTERN.search(value) else value


def pdf_flowables(value, base_style):
    """Render safe paragraphs and nested lists without exposing HTML in the PDF."""
    from reportlab.lib.enums import TA_LEFT, TA_CENTER, TA_RIGHT, TA_JUSTIFY
    from reportlab.lib.styles import ParagraphStyle
    from reportlab.platypus import Paragraph

    root = parse_html(editor_html(value or 'Belum diisi.'))
    result = []
    alignments = {'left': TA_LEFT, 'center': TA_CENTER, 'right': TA_RIGHT, 'justify': TA_JUSTIFY}

    def inline(node):
        if isinstance(node, str):
            return escape(node)
        if node.tag == 'br':
            return '<br/>'
        content = ''.join(inline(child) for child in node.children)
        tag = {'strong': 'b', 'em': 'i'}.get(node.tag, node.tag)
        return f'<{tag}>{content}</{tag}>' if tag in {'b', 'i', 'u'} else content

    def walk(node, depth=0, prefix='', inherited=None):
        attrs = dict(inherited or {})
        attrs.update(dict(part.split(':', 1) for part in node.attrs.get('style', '').split(';') if ':' in part))
        if node.tag == 'blockquote':
            depth += 2
        if node.tag in {'ul', 'ol'}:
            number = int(node.attrs.get('start', '1'))
            from reportlab.pdfbase.pdfmetrics import stringWidth
            items = [c for c in node.children if isinstance(c, Node) and c.tag == 'li']
            section = node.attrs.get('data-section')
            labels = [(f'{section}.{n}.' if section else f'{n}.') if node.tag == 'ol' else '\u2022'
                      for n in range(number, number + len(items))]
            width = max([stringWidth(label, base_style.fontName, base_style.fontSize)
                         for label in labels] or [0])
            attrs['_list_indent'] = str(depth * 16 + width + 9)
            for child in node.children:
                if isinstance(child, Node) and child.tag == 'li':
                    section = node.attrs.get('data-section')
                    bullet = (f'{section}.{number}.' if section else f'{number}.') if node.tag == 'ol' else '\u2022'
                    walk(child, depth+1, bullet, attrs)
                    number += 1
            return
        pending = []
        first = True

        def flush():
            nonlocal first
            content = ''.join(inline(child) for child in pending).strip()
            pending.clear()
            if not content:
                return
            indent = depth*16 + int(attrs.get('margin-left', '0px')[:-2])*.75
            from reportlab.pdfbase.pdfmetrics import stringWidth
            if '_list_indent' in attrs:
                indent = max(indent, float(attrs['_list_indent']))
            if prefix:
                indent = max(indent, max(0, (depth-1)*16) + stringWidth(prefix, base_style.fontName, base_style.fontSize) + 9)

            style = ParagraphStyle('SMTRich', parent=base_style,
                                   alignment=(
                                       TA_JUSTIFY
                                       if attrs.get('text-align') in {None, 'left', 'justify'}
                                       else alignments.get(attrs.get('text-align'), base_style.alignment)
                                   ),
                                   leftIndent=indent, bulletIndent=max(0, (depth-1)*16),
                                   fontName='Helvetica-Bold' if node.tag in {'h3', 'h4'} else base_style.fontName)
            result.append(Paragraph(content, style, bulletText=prefix if first and prefix else None))
            first = False

        for child in node.children:
            if isinstance(child, Node) and child.tag in BLOCKS:
                flush()
                walk(child, depth, prefix if first else '', attrs)
                first = False
            else:
                pending.append(child)
        flush()

    walk(root)
    return result or [Paragraph('-', base_style)]
