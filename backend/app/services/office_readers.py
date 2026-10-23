"""Local OOXML evidence readers. No Office executable, macros or formula execution."""
import io
import posixpath
from pathlib import Path
from zipfile import ZipFile, BadZipFile
from xml.etree import ElementTree as ET

from backend.app.services.ingestion_errors import IngestionError

W = '{http://schemas.openxmlformats.org/wordprocessingml/2006/main}'
S = '{http://schemas.openxmlformats.org/spreadsheetml/2006/main}'
R = '{http://schemas.openxmlformats.org/officeDocument/2006/relationships}'
P = '{http://schemas.openxmlformats.org/package/2006/relationships}'
MAX_EXPANDED_BYTES = 512 * 1024 * 1024
MAX_XML_BYTES = 64 * 1024 * 1024


def office_content(source, path):
    from backend.app.services.ingestion_content import PreparedContent
    suffix = Path(source.display_filename).suffix.lower()
    try:
        with ZipFile(path) as archive:
            infos = archive.infolist()
            names = {entry.filename for entry in infos}
            if len(names) != len(infos) or len(infos) > 10000 or sum(i.file_size for i in infos) > MAX_EXPANDED_BYTES:
                raise IngestionError('OFFICE_RESOURCE_LIMIT', 'Office package exceeds safe local expansion limits or has duplicate members. Original is retained.')
            if any(i.flag_bits & 1 or i.filename.startswith('/') or '..' in i.filename.split('/') for i in infos):
                raise IngestionError('OFFICE_INVALID', 'Encrypted or unsafe Office package. Upload an unlocked readable copy.')
            if any('/embeddings/' in name or '/charts/' in name or '/diagrams/' in name for name in names):
                raise IngestionError('OFFICE_CONTENT_UNSUPPORTED', 'Embedded Office objects, charts or SmartArt need a PDF export for complete visual interpretation. No partial extraction was accepted.')
            def xml(name):
                if archive.getinfo(name).file_size > MAX_XML_BYTES:
                    raise IngestionError('OFFICE_RESOURCE_LIMIT', 'An Office XML part exceeds the local parser limit. Original is retained.')
                data = archive.read(name)
                if b'<!DOCTYPE' in data.upper() or b'<!ENTITY' in data.upper():
                    raise IngestionError('OFFICE_INVALID', 'Office XML declarations are unsupported.')
                return ET.fromstring(data)
            attachments = []
            image_notes = []
            for name in sorted(names):
                if name.startswith(('word/media/', 'xl/media/')) and not name.endswith('/'):
                    from PIL import Image, UnidentifiedImageError
                    try:
                        with Image.open(io.BytesIO(archive.read(name))) as original:
                            if getattr(original, 'n_frames', 1) != 1:
                                raise IngestionError('OFFICE_CONTENT_UNSUPPORTED', 'Animated embedded images need a PDF export.')
                            image = original.convert('RGB')
                            try:
                                output = io.BytesIO(); image.save(output, 'PNG')
                            finally:
                                image.close()
                        attachments.append({'media_type': 'image/png', 'data': output.getvalue(),
                                            'source_label': 'Embedded image '+name+'. Use its package path as source_locator; do not invent a page number.'})
                        image_notes.append(name)
                    except (UnidentifiedImageError, OSError, Image.DecompressionBombError) as exc:
                        raise IngestionError('OFFICE_CONTENT_UNSUPPORTED', 'An embedded image cannot be decoded. Export to PDF instead of silently omitting it.') from exc
            if suffix == '.docx':
                lines, locators = [], []
                parts = ['word/document.xml'] + sorted(name for name in names if
                    name.startswith(('word/header', 'word/footer')) and name.endswith('.xml'))
                parts += [name for name in ('word/footnotes.xml', 'word/endnotes.xml', 'word/comments.xml') if name in names]
                for part in parts:
                    root = xml(part)
                    parents = {child: parent for parent in root.iter() for child in parent}
                    table_rows = {row: number for number, row in enumerate(root.iter(W+'tr'), 1)}
                    # Every paragraph, including table cells and text boxes, remains
                    # in XML order. OOXML does not supply stable rendered pages.
                    for number, paragraph in enumerate(root.iter(W+'p'), 1):
                        text = ''.join(node.text or '' if node.tag == W+'t' else '\t' if node.tag == W+'tab' else '\n'
                                       for node in paragraph.iter() if node.tag in (W+'t', W+'tab', W+'br', W+'cr'))
                        if not text.strip(): continue
                        locator = f'{part}#paragraph-{number}'
                        ancestor = paragraph
                        cell = None
                        while ancestor in parents:
                            ancestor = parents[ancestor]
                            if ancestor.tag == W+'tc': cell = ancestor
                            if ancestor.tag == W+'tr': break
                        context = ''
                        if cell is not None and ancestor.tag == W+'tr':
                            context = f" table-row={table_rows[ancestor]} cell={list(ancestor).index(cell)+1}"
                        locators.append(locator); lines.append(f'[{locator}{context}] {text}')
                if any(name.startswith('word/') and name.endswith('.xml') and b'altChunk' in archive.read(name) for name in parts):
                    raise IngestionError('OFFICE_CONTENT_UNSUPPORTED', 'Imported external document parts need a PDF export.')
                text = '\n'.join(lines)
                cells = None; kind = 'TEXT'
                metadata = {'format': 'DOCX', 'locators': locators, 'embedded_images': image_notes,
                            'rendered_pages': False, 'coverage': 'Paragraphs including tables, headers, footers, notes and comments; embedded images supplied separately.'}
                metadata['tracked_changes'] = 'Inserted text included; deleted text omitted. Revision acceptance must be checked against the original.'
            else:
                workbook = xml('xl/workbook.xml')
                relationships = {rel.attrib['Id']: rel.attrib for rel in xml('xl/_rels/workbook.xml.rels')}
                strings = []
                if 'xl/sharedStrings.xml' in names:
                    strings = [''.join(node.text or '' for node in item.iter(S+'t')) for item in xml('xl/sharedStrings.xml').findall(S+'si')]
                formats = {}; styles = []
                if 'xl/styles.xml' in names:
                    style_xml = xml('xl/styles.xml')
                    formats = {n.attrib['numFmtId']: n.attrib['formatCode'] for n in style_xml.findall(S+'numFmts/'+S+'numFmt')}
                    styles = [n.attrib.get('numFmtId', '0') for n in style_xml.findall(S+'cellXfs/'+S+'xf')]
                cells = [['sheet', 'cell', 'value', 'formula', 'number_format', 'row_hidden']]
                sheets, locators, missing = [], [], []
                for sheet in workbook.findall(S+'sheets/'+S+'sheet'):
                    relation = relationships[sheet.attrib[R+'id']]
                    if relation.get('TargetMode') == 'External':
                        raise IngestionError('OFFICE_CONTENT_UNSUPPORTED', 'External worksheet content cannot be read locally.')
                    target = relation['Target']
                    member = target.lstrip('/') if target.startswith('/') else posixpath.normpath('xl/'+target)
                    if not member.startswith('xl/worksheets/'):
                        raise IngestionError('OFFICE_CONTENT_UNSUPPORTED', 'A non-worksheet sheet needs a PDF export.')
                    name = sheet.attrib['name']; sheets.append({'name': name, 'visibility': sheet.attrib.get('state', 'visible')})
                    root = xml(member)
                    for row in root.findall(S+'sheetData/'+S+'row'):
                        for cell in row.findall(S+'c'):
                            address = cell.attrib['r']; value = cell.findtext(S+'v', '')
                            cell_type = cell.attrib.get('t', 'n')
                            if cell_type == 's': value = strings[int(value)]
                            elif cell_type == 'inlineStr': value = ''.join(n.text or '' for n in cell.iter(S+'t'))
                            formula = cell.find(S+'f')
                            if formula is not None:
                                formula_text = '='+(formula.text or '[shared formula, see anchor]')
                                if value == '': missing.append(f"'{name}'!{address}")
                            else: formula_text = ''
                            if not value and not formula_text: continue
                            style = int(cell.attrib.get('s', '0'))
                            fmt_id = styles[style] if style < len(styles) else '0'
                            fmt = formats.get(fmt_id, 'builtin:'+fmt_id)
                            locator = f"'{name}'!{address}"; locators.append(locator)
                            cells.append([name, address, value, formula_text, fmt, row.attrib.get('hidden', '0')])
                    for merge in root.findall(S+'mergeCells/'+S+'mergeCell'):
                        cells.append([name, merge.attrib['ref'], '[merged range; value belongs to anchor cell]', '', '', ''])
                date_system = workbook.find(S+'workbookPr')
                metadata = {'format': 'XLSX' if suffix == '.xlsx' else 'XLSM', 'sheets': sheets, 'locators': locators,
                            'embedded_images': image_notes, 'date_system': '1904' if date_system is not None and date_system.attrib.get('date1904') in ('1', 'true') else '1900',
                            'formulas_without_cached_values': missing, 'formula_execution': False,
                            'coverage': 'All populated cells in all sheets, including hidden sheets/rows. Formula text and cached values are separate; cache freshness is unknown.'}
                text = None; kind = 'CELLS'
            if not locators and not attachments:
                raise IngestionError('OFFICE_EMPTY', 'No readable text, cells or images were found in this Office file.')
            media = {'.docx':'application/vnd.openxmlformats-officedocument.wordprocessingml.document',
                     '.xlsx':'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
                     '.xlsm':'application/vnd.ms-excel.sheet.macroEnabled.12'}[suffix]
            return PreparedContent(source.id, kind, media,
                                   text=text, cells=cells, attachments=attachments, metadata=metadata)
    except IngestionError:
        raise
    except (BadZipFile, ET.ParseError, KeyError, IndexError, ValueError, RuntimeError) as exc:
        raise IngestionError('OFFICE_INVALID', 'The Office file is damaged, encrypted or is not a supported OOXML document. Original is retained.') from exc
