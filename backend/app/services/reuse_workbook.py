"""Formatted Excel snapshots of Terra's saved reuse facts and impact results."""
from datetime import datetime
from decimal import Decimal
from io import BytesIO
import re
import textwrap

import xlsxwriter

from backend.app.services.impact_service import ImpactError, ImpactInvalid
from backend.app.services.reuse_report import build_reuse_report, ZONE, _input

MIME='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet'
NUMBER='#,##0.0#####;[Red](#,##0.0#####);0'
CARBON='#,##0.00;[Red](#,##0.00);0.00'
FOREST='#194E3D'


def report_filename(report):
    name=re.sub(r'[^A-Za-z0-9_-]+','-',report['scope']['project_code']).strip('-')[:70] or 'project'
    return f'terra-{name}-reuse-{report["generated_at"][:10]}.xlsx'


def write_workbook(report):
    """All outputs are as-at values, never editable stock or live recalculation."""
    buffer=BytesIO()
    wb=xlsxwriter.Workbook(buffer,{'in_memory':True,'strings_to_formulas':False,'strings_to_urls':False})
    wb.set_properties({'title':'Terra material reuse and impact','subject':report['scope']['project_name'],'author':'Terra','comments':'Read-only cumulative reporting snapshot'})
    formats={
        'body':wb.add_format({'font_name':'Arial','font_size':10,'font_color':'#233D32','valign':'vcenter'}),
        'wrap':wb.add_format({'font_name':'Arial','font_size':10,'font_color':'#233D32','text_wrap':True,'valign':'top'}),
        'title':wb.add_format({'font_name':'Arial','font_size':16,'bold':True,'font_color':FOREST,'bottom':1,'bottom_color':'#C7D7C9'}),
        'heading':wb.add_format({'font_name':'Arial','font_size':10,'bold':True,'font_color':'#FFFFFF','bg_color':FOREST,'text_wrap':True,'align':'center','valign':'vcenter','right':1,'right_color':'#FFFFFF'}),
        'label':wb.add_format({'font_name':'Arial','font_size':10,'bold':True,'font_color':FOREST,'valign':'vcenter'}),
        'note':wb.add_format({'font_name':'Arial','font_size':10,'font_color':'#587064','text_wrap':True,'valign':'top'}),
        'number':wb.add_format({'font_name':'Arial','font_size':10,'num_format':NUMBER,'valign':'vcenter'}),
        'integer':wb.add_format({'font_name':'Arial','font_size':10,'num_format':'#,##0;[Red](#,##0);0','valign':'vcenter'}),
        'carbon':wb.add_format({'font_name':'Arial','font_size':10,'num_format':CARBON,'valign':'vcenter'}),
        'date':wb.add_format({'font_name':'Arial','font_size':10,'num_format':'dd mmm yyyy hh:mm','valign':'vcenter'}),
        'date_only':wb.add_format({'font_name':'Arial','font_size':10,'num_format':'dd mmm yyyy','valign':'vcenter'}),
        'link':wb.add_format({'font_name':'Arial','font_size':10,'font_color':FOREST,'underline':1,'valign':'vcenter'}),
        'warn':wb.add_format({'font_name':'Arial','font_size':10,'font_color':'#805415','bg_color':'#FFF3D9','text_wrap':True}),
        'negative':wb.add_format({'font_color':'#A33226','bg_color':'#FDEAE5'}),
    }
    text_precision=False
    def cell(ws,r,c,value,style='body'):
        nonlocal text_precision
        fmt=formats[style]
        if value is None or value=='':ws.write_blank(r,c,None,fmt)
        elif isinstance(value,(int,float,Decimal)) and not isinstance(value,bool):
            number=Decimal(str(value))
            if not number.is_finite():raise ImpactError('REPORT_NUMBER_INVALID','A report value is not finite. No workbook was exported.')
            if len(number.normalize().as_tuple().digits)>15:
                text_precision=True;ws.write_string(r,c,format(number,'f'),fmt)
            else:
                if style in ('body','number'):fmt=formats['integer' if number==number.to_integral_value() else 'number']
                ws.write_number(r,c,float(number),fmt)
        elif isinstance(value,datetime):ws.write_datetime(r,c,value,formats['date'])
        else:
            text=str(value)
            if len(text)>32767:raise ImpactInvalid('REPORT_TEXT_TOO_LONG','A report field exceeds Excel’s cell capacity. No data was truncated.')
            ws.write_string(r,c,text,fmt)
    def date_cell(ws,r,c,value):
        if not value:return cell(ws,r,c,None)
        parsed=datetime.fromisoformat(str(value).replace('Z','+00:00'))
        if parsed.tzinfo:parsed=parsed.astimezone(ZONE).replace(tzinfo=None)
        cell(ws,r,c,parsed,'date')
    sheet_widths={}
    def sheet(name,title,widths):
        ws=wb.add_worksheet(name);ws.hide_gridlines(2);ws.set_zoom(90);ws.set_default_row(22)
        sheet_widths[name]=widths
        ws.set_column(0,0,3)
        for col,width in enumerate(widths,1):ws.set_column(col,col,width,formats['body'])
        ws.merge_range(1,1,1,len(widths),title,formats['title']);ws.set_row(1,28)
        ws.merge_range(2,1,2,len(widths),report['scope']['project_name'],formats['label'])
        ws.merge_range(3,1,3,len(widths),'Current cumulative position. Dates shown in Malaysia time.',formats['note'])
        ws.set_landscape();ws.set_paper(8 if len(widths)>9 else 9);ws.fit_to_pages(2 if len(widths)>12 else 1,0)
        ws.set_margins(.3,.3,.4,.4);ws.set_footer('&LTerra material reuse report&RPage &P of &N')
        ws.set_tab_color(FOREST if name=='Summary' else '#91AC92' if name in ('Transfers','Carbon breakdown') else '#B89B64')
        return ws
    def table(ws,headers,records,start=5,styles=None,freeze=True):
        for col,label in enumerate(headers,1):cell(ws,start,col,label,'heading')
        ws.set_row(start,42)
        if not records:
            ws.merge_range(start+1,1,start+1,len(headers),'No records in this scope.',formats['note']);ws.set_row(start+1,30)
        for offset,values in enumerate(records,start+1):
            lines=1
            for col,value in enumerate(values,1):
                style=(styles or {}).get(col,'wrap' if col in (2,3,4) else 'body')
                if style in ('wrap','note','warn') and isinstance(value,str):
                    width=max(8,int(sheet_widths[ws.get_name()][col-1]*.85))
                    value='\n'.join(part for original in value.split('\n') for part in (textwrap.wrap(original,width=width,break_long_words=False) or ['']))
                    lines=max(lines,value.count('\n')+1)
                if style=='date':date_cell(ws,offset,col,value)
                else:cell(ws,offset,col,value,style)
            ws.set_row(offset,min(409,max(28,lines*14+8)))
        if records:ws.autofilter(start,1,start+len(records),len(headers))
        if freeze:ws.freeze_panes(start+1,3)
        ws.repeat_rows(start,start)
        ws.print_area(0,1,start+max(1,len(records)),len(headers))
        return start+1

    summary=sheet('Summary','Material reuse and impact',[43,14,16,15,15,15,17,18])
    transfers=sheet('Transfers','Transfer register',[10,45,32,32,14,9,15,15,15,15,17,17,22,22,22,22])
    carbon=sheet('Carbon breakdown','Saved carbon calculations',[10,40,15,15,9,17,16,18,19,17,18,18,19,20,20,20,20,22,23])
    references=sheet('Factors & evidence','Factors and supporting evidence',[10,18,30,23,18,55,18,18,40,34,48])
    attention=sheet('Needs attention','Information to resolve',[10,40,25,55,55])
    overview=report['summary'];used_count=overview['used_transfers'];covered=overview['complete_estimates']
    cell(summary,4,1,'Generated (Malaysia time)','label');date_cell(summary,4,3,report['generated_at'])
    metrics=[('Transfers in this report',overview['transfers'],'number'),('Transfers with actual use',used_count,'number'),
        ('Known actual reused mass (tonnes)',overview['known_reuse_tonnes'],'number'),
        ('Used transfers with unknown weight',overview['unknown_mass_transfers'],'number'),
        ('Known net estimate (kgCO₂e)',overview['known_net_kgco2e'],'carbon'),
        ('Complete carbon estimates',f'{covered} of {used_count} used transfers','body'),
        ('Demonstration-factor subtotal',overview['net_by_factor_basis']['Demonstration'],'carbon'),
        ('Mixed-factor subtotal',overview['net_by_factor_basis']['Mixed'],'carbon'),
        ('Other-factor subtotal',overview['net_by_factor_basis']['Other factors'],'carbon')]
    for r,(label,value,style) in enumerate(metrics,7):cell(summary,r,1,label,'label');cell(summary,r,3,value,style)
    notes=[report['notice'],
        'Production avoidance uses actual use. Freight and handling use moved quantity.',
        'Missing and pending estimates are excluded from the known net subtotal; see Needs attention.',
        'Project reports share transfer outcomes. Do not sum separate project reports.' if report['scope']['project_id'] else 'Each transfer is counted once across all projects.']
    for r,note in enumerate(notes,17):
        summary.merge_range(r,1,r,8,note,formats['note']);summary.set_row(r,26)
    material_rows=[[f'M{i:02} '+r['material']+(f" / {r['role']}" if report['scope']['project_id'] else ''),r['unit'],r['used'],r['dispatched'],r['received'],r['unused'],r['known_mass_tonnes'],
        f"{r['unknown_mass_transfers']} unknown weight" if r['unknown_mass_transfers'] else ''] for i,r in enumerate(report['materials'],1)]
    table(summary,['Material','Unit','Used','Dispatched','Received','Received unused','Known mass (t)','Coverage'],material_rows,start=23,
        styles={1:'wrap',2:'body',3:'number',4:'number',5:'number',6:'number',7:'number',8:'note'},freeze=False)

    transfer_rows=[];carbon_rows=[];reference_rows=[];reference_locations={}
    def reference(ref,section,item,value='',unit_name='',basis='',version='',valid='',locator='',provenance='',technical=''):
        reference_rows.append([ref,section,item,value,unit_name,basis,version,valid,locator,provenance,technical])
    for row in report['transfers']:
        reference_locations[row['ref']]=len(reference_rows)+7
        transfer_rows.append([row['ref'],row['material'],row['source'],row['recipient'],row['role'],row['unit'],row['reserved'],row['dispatched'],row['received'],row['used'],row['unused'],row['state'],row['confirmed_at'],row['dispatched_at'],row['received_at'],row['used_at']])
        assessment=row['assessment'];factors={f['factor_type']:f for f in row['factors']}
        production=factors.get('NEW_MATERIAL_PRODUCTION',{});freight=factors.get('TRANSPORT',{});handling=factors.get('PROCESSING',{})
        if row['used']:
            carbon_rows.append([row['ref'],row['material'],row['used'],row['dispatched'],row['unit'],row['carbon_weight'],row['distance'],
                production.get('value'),production.get('unit'),freight.get('value'),freight.get('unit'),handling.get('value'),handling.get('unit'),
                assessment.get('avoided_production_kgco2e') if assessment else None,assessment.get('additional_transport_kgco2e') if assessment else None,
                assessment.get('additional_processing_kgco2e') if assessment else None,assessment.get('net_avoided_kgco2e') if assessment else None,
                row['assessment_status'],row['factor_kind']])
        reference(row['ref'],'Identity','Transfer',technical=row['transfer_id'])
        reference(row['ref'],'Identity','Catalogue material',technical=row['material_id'])
        reference(row['ref'],'Identity','Source project',row['source'],technical=row['source_id'])
        reference(row['ref'],'Identity','Recipient project',row['recipient'],technical=row['recipient_id'])
        if assessment:
            reference(row['ref'],'Assessment','Current saved assessment',basis=assessment['baseline_description'],version=row['revision'],
                valid=assessment['calculated_at'],provenance=row['assessment_status'],technical=assessment['id'])
            reference(row['ref'],'Assessment','Calculation boundary',basis=assessment.get('assumptions',{}).get('lifecycle_boundary','Not recorded'))
        for key,value in row['specifications'].items():
            reference(row['ref'],'Specification',str(key).replace('_',' ').capitalize(),', '.join(map(str,value)) if isinstance(value,list) else value)
        reference(row['ref'],'Weight','Current catalogue unit weight',row['current_mass_kg_per_unit'],'kg/'+row['unit'],
            basis='Used for the mass summary. Carbon inputs below retain the saved assessment basis.')
        if assessment:
            reference(row['ref'],'Weight','Saved carbon unit weight',row['carbon_weight'],'kg/'+row['unit'],basis=_input(assessment,'mass_source','Not recorded'))
            reference(row['ref'],'Route','Saved route distance',row['distance'],'km',basis=_input(assessment,'route_assumption',assessment.get('assumptions',{}).get('route_assumption','Not recorded')),
                technical=_input(assessment,'route_id',assessment.get('assumptions',{}).get('symmetric_route_id','')))
        for factor in row['factors']:
            label=factor['factor_type'].replace('_',' ').capitalize()
            source=factor.get('source_label','Not recorded')+(' / '+factor['source_url'] if factor.get('source_url') else '')
            reference(row['ref'],'Factor',label,factor['value'],factor['unit'],source,factor.get('version'),factor.get('valid_from'),factor.get('geography'),
                'Demonstration assumption' if factor.get('is_demo_factor') else 'Not marked demonstration; not independently verified',factor['id'])
        for note in row['provenance']:reference(row['ref'],'Input basis','Provenance',basis=note)
        for evidence in row['evidence']:reference(row['ref'],'Evidence',evidence['role'],basis=evidence['label'],valid=evidence.get('recorded_at'),locator=evidence['locator'],provenance=evidence['kind'],technical=evidence['reference'])
    table(transfers,['Ref','Material','Source project','Recipient project','Project role','Unit','Reserved now','Dispatched','Received','Used','Received unused','State','Reserved on','Dispatched on','Received on','Latest use on'],transfer_rows,
        styles={1:'link',2:'wrap',3:'wrap',4:'wrap',**{i:'number' for i in range(7,12)},**{i:'date' for i in range(13,17)}})
    table(carbon,['Ref','Material','Used quantity','Moved quantity','Unit','Weight kg/unit','Distance km','Production factor','Production unit','Freight factor','Freight unit','Handling factor','Handling unit','Production avoided kgCO₂e','Freight kgCO₂e','Handling kgCO₂e','Net avoided kgCO₂e','Coverage','Factor basis'],carbon_rows,
        styles={1:'body',2:'wrap',**{i:'number' for i in (3,4,6,7,8,10,12)},**{i:'carbon' for i in (14,15,16,17)},18:'wrap',19:'wrap'})
    table(references,['Ref','Section','Item','Value','Unit','Source or basis','Version / revision','Date','Location or page','Provenance','Technical reference'],reference_rows,
        styles={1:'body',2:'body',3:'wrap',4:'wrap',6:'wrap',8:'date',9:'wrap',10:'wrap',11:'wrap'})
    table(attention,['Ref','Material','Status','Missing information / concern','Next action'],[[r[k] for k in ('ref','material','status','details','action')] for r in report['issues']],
        styles={1:'body',2:'wrap',3:'warn',4:'wrap',5:'wrap'})
    if not report['issues']:cell(attention,6,1,'No unresolved reporting inputs for used transfers in this scope.','note')
    for ws,values in ((transfers,transfer_rows),(carbon,carbon_rows)):
        for offset,row in enumerate(values,6):
            ws.write_url(offset,1,f"internal:'Factors & evidence'!B{reference_locations[row[0]]}",formats['link'],row[0])
    transfer_locations={r['ref']:i+7 for i,r in enumerate(report['transfers'])}
    for offset,issue in enumerate(report['issues'],6):
        attention.write_url(offset,1,f"internal:'Transfers'!B{transfer_locations[issue['ref']]}",formats['link'],issue['ref'])
    if text_precision:
        row=6+len(reference_rows)
        references.merge_range(row,1,row,10,'Exact values exceeding Excel’s 15 significant digits are stored as text, without rounding.',formats['note'])
        references.set_row(row,28);references.print_area(0,1,row,11)
    if carbon_rows:
        carbon.conditional_format(6,17,5+len(carbon_rows),17,{'type':'cell','criteria':'<','value':0,'format':formats['negative']})
    # Bar chart reads only the known net subtotal for each material; quantities
    # in different units are never placed on a common quantity axis.
    chart_rows=[(i,r) for i,r in enumerate(report['materials'],1) if r['complete']]
    if chart_rows:
        chart=wb.add_chart({'type':'bar'})
        for index,(number,item) in enumerate(chart_rows,7):
            cell(summary,index,11,f'M{number:02}','body');cell(summary,index,12,item['known_net'],'carbon')
        summary.set_column(11,12,None,None,{'hidden':True})
        chart.add_series({'name':'Known net estimate','categories':['Summary',7,11,6+len(chart_rows),11],
            'values':['Summary',7,12,6+len(chart_rows),12],'fill':{'color':FOREST},'border':{'none':True},'invert_if_negative':True,'invert_if_negative_color':'#A33226'})
        chart.show_hidden_data();chart.set_title({'name':'Known net estimate by material','name_font':{'name':'Arial','size':11}})
        chart.set_x_axis({'name':'kgCO₂e','num_font':{'name':'Arial','size':9},'name_font':{'name':'Arial','size':9},'major_gridlines':{'visible':True,'line':{'color':'#E2E9DF'}}})
        chart.set_y_axis({'num_font':{'name':'Arial','size':9}});chart.set_legend({'none':True})
        chart.set_chartarea({'border':{'none':True}});chart.set_plotarea({'border':{'none':True}})
        chart.set_size({'width':410,'height':230})
        summary.insert_chart('F7',chart,{'x_offset':5,'y_offset':0})
        summary.merge_range(21,5,21,8,'Material references are listed below.',formats['note'])
    wb.close()
    return buffer.getvalue()


def export_reuse_excel(repository=None, *, project_id=None, transfer_id=None, clock=None):
    report=build_reuse_report(repository,project_id=project_id,transfer_id=transfer_id,clock=clock)
    return write_workbook(report),report_filename(report)
