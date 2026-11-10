"""Semantic, period-aware readers. No database access or positional schema guesses."""
import re
import zipfile
from decimal import Decimal,InvalidOperation
from openpyxl import load_workbook
from openpyxl.utils import get_column_letter
MONTHS=['','januari','februari','maret','april','mei','juni','juli','agustus','september','oktober','november','desember']
ALIASES={'jan':1,'feb':2,'mar':3,'apr':4,'may':5,'jun':6,'jul':7,'aug':8,'agu':8,'sep':9,'oct':10,'okt':10,'nov':11,'dec':12,'des':12,'nopember':11}
FIELDS={
 'no risiko':'code','nomor risiko':'code','kode risiko':'code','peristiwa risiko':'title','nama peristiwa risiko':'title',
 'kode penyebab risiko':'cause_code','kode penyebab':'cause_code','jenis risiko':'kind',
 'asumsi perhitungan dampak':'realisasi_asumsi_dampak','nilai dampak':'realisasi_nilai_dampak',
 'skala dampak':'realisasi_skala_dampak_id','nilai probabilitas':'realisasi_nilai_probabilitas',
 'skala probabilitas':'realisasi_skala_probabilitas_id','nilai eksposur risiko':'realisasi_eksposur',
 'skala nilai risiko':'realisasi_skor_risiko','level risiko':'realisasi_level_risiko_bumn',
 'realisasi rencana perlakuan risiko':'realisasi_rencana_perlakuan',
 'realisasi output atas masing masing breakdown perlakuan risiko':'realisasi_output_perlakuan',
 'realisasi output perlakuan risiko':'realisasi_output_perlakuan',
 'realisasi biaya perlakuan risiko rp usd':'realisasi_biaya_perlakuan',
 'persentase serapan biaya':'persentase_serapan_biaya',
 'realisasi biaya perlakuan risiko':'realisasi_biaya_perlakuan','realisasi pic':'realisasi_pic',
 'status rencana perlakuan risiko':'status_rencana_perlakuan','penjelasan status rencana perlakuan':'penjelasan_status_rencana',
 'progress pelaksanaan rencana perlakuan':'progress_pelaksanaan_percent','progres pelaksanaan rencana perlakuan':'progress_pelaksanaan_percent',
 'key risk indicators':'kri_name','key risk indicator':'kri_name','unit satuan kri':'kri_unit','satuan kri':'kri_unit',
 'efektifitas perlakuan risiko':'efektivitas_perlakuan_risiko','efektivitas perlakuan risiko':'efektivitas_perlakuan_risiko',
}
NUMERIC={'realisasi_nilai_dampak','realisasi_nilai_probabilitas','realisasi_eksposur','realisasi_biaya_perlakuan','progress_pelaksanaan_percent','persentase_serapan_biaya'}
def norm(value):return re.sub(r'\s+',' ',re.sub(r'[^a-z0-9]+',' ',str(value or '').casefold())).strip()
def code(value):return re.sub('[^A-Z0-9]','',str(value or '').upper())
def month_in(value):
 tokens=norm(value).split();found={i for i,name in enumerate(MONTHS) if i and name in tokens}
 found.update(ALIASES[t] for t in tokens if t in ALIASES)
 return found

def decimal_value(value,number_format='',percent=False):
 if value is None or value=='':return None
 if isinstance(value,bool):raise ValueError('Nilai boolean bukan angka realisasi.')
 if isinstance(value,(float,int,Decimal)):v=Decimal(str(value));formatted='%' in number_format
 else:
  s=str(value).strip().replace('\xa0','').replace('Rp','').replace(' ','');explicit=s.endswith('%');s=s.rstrip('%')
  if ',' in s and '.' in s:s=s.replace('.','').replace(',','.') if s.rfind(',')>s.rfind('.') else s.replace(',','')
  elif ',' in s:
   if re.fullmatch(r'[+-]?\d{1,3}(?:,\d{3})+',s):raise ValueError('Pemisah koma ambigu; gunakan sel angka Excel: '+str(value))
   s=s.replace(',','.')
  if re.fullmatch(r'[+-]?\d{1,3}(?:\.\d{3})+',s):raise ValueError('Pemisah titik ambigu; gunakan sel angka Excel atau pemisah desimal yang jelas: '+str(value))
  try:v=Decimal(s)
  except InvalidOperation as exc:raise ValueError('Nilai bukan angka tunggal: '+str(value)) from exc
  formatted=False
 if not v.is_finite():raise ValueError('NaN/Infinity tidak dapat diimpor.')
 if percent and formatted:v*=100
 return v

def section_sheet(workbook,section):
 names=[n for n in workbook.sheetnames if norm(n).endswith('iii '+section.lower())]
 if len(names)!=1:raise ValueError('Sheet III.'+section+' tidak tunggal/ditemukan. Nama sheet boleh memakai awalan LAP REAL.')
 return workbook[names[0]]

def anchor(ws):
 positions=[];metadata=[]
 for row in ws.iter_rows(max_row=min(ws.max_row,25)):
  for cell in row:
   if norm(cell.value)=='start pengisian':positions.append(cell.row)
   if norm(cell.value) in ('notes','petunjuk','jenis data'):metadata.append(cell.row)
 if metadata:positions.append(max(metadata)+1)
 if positions:return min(positions)
 raise ValueError('Awal data tidak ditemukan pada '+ws.title)

def merged_span(ws,row,col):
 for rg in ws.merged_cells.ranges:
  if rg.min_row<=row<=rg.max_row and rg.min_col<=col<=rg.max_col:return rg.min_col,rg.max_col,ws.cell(rg.min_row,rg.min_col).value
 return col,col,ws.cell(row,col).value

def context(ws,row,col):return [str(merged_span(ws,r,col)[2] or '') for r in range(1,row+1)]
def choose_columns(ws,start,section,month,year):
 quarter=(month-1)//3+1;candidates={};warnings=[];seen=set()
 for row in ws.iter_rows(max_row=start-1):
  for cell in row:
   if cell.value is None or len(str(cell.value))>160:continue
   label=norm(cell.value);field=FIELDS.get(label)
   if field is None:
    if label.startswith('realisasi rencana perlakuan risiko'):field='realisasi_rencana_perlakuan'
    elif label.startswith('realisasi threshold kri'):field='kri_group'
    elif label.startswith('asumsi perhitungan dampak') and section=='A':field='realisasi_asumsi_dampak'
   if not field:continue
   left,right,_=merged_span(ws,cell.row,cell.column)
   ctx=context(ws,cell.row,cell.column)
   if section=='A' and field not in {'code','title','kind'}:
    if 'inheren' in ' '.join(ctx).casefold():continue
    if field.startswith('realisasi_') and field!='efektivitas_perlakuan_risiko' and not any('residual' in s.casefold() for s in ctx):continue
   months=set().union(*(month_in(s) for s in ctx))
   if months and month not in months:continue
   years={int(y) for s in ctx for y in re.findall(r'\b20\d{2}\b',s)}
   if years and year not in years:continue
   if any('kbumn' in norm(s).split() for s in ctx) and section=='A':continue
   cols=[]
   for col in range(left,right+1):
    q=[]
    for r in range(cell.row+1,min(start,cell.row+5)):
     v=norm(ws.cell(r,col).value)
     if re.fullmatch(r'q[1-4]',v):q.append(int(v[-1]))
    if q and quarter not in q:continue
    if q and not (section=='A' and any('kbumn' in norm(merged_span(ws,rr,col)[2]).split() for rr in range(cell.row+1,min(start,cell.row+4)))):cols.append(col)
   if field=='kri_group':
    children={norm(ws.cell(r,c).value):c for r in range(cell.row+1,min(start,cell.row+4)) for c in range(left,right+1) if norm(ws.cell(r,c).value) in {'threshold','skor','nilai','aktual'}}
    status=children.get('threshold');actual=children.get('skor') or children.get('nilai') or children.get('aktual')
    if status and actual:
     candidates.setdefault('kri_status',set()).add(status);candidates.setdefault('kri_actual',set()).add(actual)
    else:warnings.append('Pasangan threshold/aktual KRI tidak dikenali pada '+cell.coordinate)
    continue
   if not cols:
    if right>left and field in NUMERIC|{'realisasi_skala_dampak_id','realisasi_skala_probabilitas_id','realisasi_skor_risiko','realisasi_level_risiko_bumn'}:
     warnings.append('Kuartal belum dapat ditentukan untuk '+str(cell.value));continue
    cols=[left]
   candidates.setdefault(field,set()).update(cols)
 result={}
 for field,cols in candidates.items():
  if len(cols)==1:result[field]=next(iter(cols))
  else:
   filled={c for c in cols if any(ws.cell(r,c).value not in (None,'') for r in range(start,ws.max_row+1))}
   if field in {'kri_status','kri_actual'} and len(filled)==1:
    result[field]=next(iter(filled));warnings.append('Header KRI periode sama berulang; hanya kolom '+get_column_letter(result[field])+' memiliki data. Periksa pemetaan ini sebelum impor.')
   else:warnings.append('Kolom '+field+' ambigu: '+', '.join(get_column_letter(c) for c in sorted(cols))+'. Tidak dibaca otomatis.')
 if section=='B' and 'realisasi_rencana_perlakuan' not in result:raise ValueError('Kolom realisasi perlakuan untuk bulan tujuan tidak tunggal/ditemukan pada '+ws.title)
 return result,warnings

def entry(ws,r,section,columns,formulas,month):
 def get(key):return ws.cell(r,columns[key]) if key in columns else None
 def value(key):return get(key).value if get(key) else None
 issues=[];errors=[];proposed={};source_cells={}
 for key,col in columns.items():
  if not key.startswith('realisasi_') and key not in {'progress_pelaksanaan_percent','status_rencana_perlakuan','penjelasan_status_rencana','efektivitas_perlakuan_risiko','persentase_serapan_biaya'}:continue
  cell=ws.cell(r,col);v=cell.value;source_cells[key]=f'{ws.title}!{cell.coordinate}'
  if v is None or v=='':
   if str(formulas.cell(r,col).value or '').startswith('='):issues.append('Formula belum memiliki hasil tersimpan: '+source_cells[key])
   continue
  if cell.data_type=='e':errors.append('Formula error '+str(v)+' pada '+source_cells[key]);continue
  try:
   if key in NUMERIC:
    if key in {'realisasi_nilai_probabilitas','progress_pelaksanaan_percent','persentase_serapan_biaya'} and isinstance(v,(int,float,Decimal)) and 0<Decimal(str(v))<=1 and '%' not in cell.number_format:issues.append('Nilai '+str(v)+' pada '+source_cells[key]+' tidak berformat persen; dibaca sebagai '+str(v)+'%, bukan dikali 100. Periksa satuannya.')
    v=decimal_value(v,cell.number_format,percent=key in {'realisasi_nilai_probabilitas','progress_pelaksanaan_percent','persentase_serapan_biaya'}).quantize(Decimal('.01'))
   elif key.endswith('_id') or key=='realisasi_skor_risiko':
    v=decimal_value(v)
    if v!=v.to_integral_value():raise ValueError('Skala harus bilangan bulat.')
    v=int(v)
   elif key=='status_rencana_perlakuan':
    t=norm(v);v='discontinue' if 'discontinue' in t else 'continue' if 'continue' in t else None
   elif key=='efektivitas_perlakuan_risiko':v='tidak_efektif' if 'tidak' in norm(v) else 'efektif' if norm(v)=='efektif' else None
   else:v=str(v).strip()
  except ValueError as exc:errors.append(str(exc)+' ('+source_cells[key]+')');continue
  if v is not None:proposed[key]=str(v) if isinstance(v,Decimal) else v
 # A calculated zero with empty inputs is not a zero realization.
 if section=='A':
  kind=norm(value('kind'))
  absent=not all(k in proposed for k in ['realisasi_nilai_dampak','realisasi_nilai_probabilitas'])
  exposure_col=columns.get('realisasi_eksposur')
  if absent and exposure_col and proposed.get('realisasi_eksposur') in ('0.00','0',0) and str(formulas.cell(r,exposure_col).value or '').startswith('='):
   proposed.pop('realisasi_eksposur',None);issues.append('Eksposur formula diabaikan karena komponen Q terpilih kosong; snapshot lama dipertahankan.')
  if not any(k in proposed for k in ['realisasi_nilai_dampak','realisasi_nilai_probabilitas','realisasi_eksposur','realisasi_skor_risiko']):
   proposed.pop('efektivitas_perlakuan_risiko',None);issues.append('Nilai risiko Q terpilih belum tersedia; tidak memakai kuartal sebelumnya atau efektivitas formula.')
 if section=='B':
  raw=value('kri_actual');status=value('kri_status')
  if raw is not None and raw!='':
   cell=get('kri_actual');text=str(raw).strip()
   if isinstance(raw,(int,float,Decimal)) and '%' in cell.number_format:text=str(decimal_value(raw,cell.number_format,percent=True))+'%'
   elif isinstance(raw,(int,float,Decimal)) and ('%' in str(value('kri_unit') or '') or norm(value('kri_unit')).startswith('persen')):text=str(raw)+'%'
   # Preserve numeric KRI as text where composite/category meanings may differ.
   proposed['realisasi_kri_text']=text;proposed['realisasi_nilai_kri']=None
   proposed['realisasi_threshold_kri']=None;proposed['realisasi_threshold_kri_skor']=None
   source_cells['realisasi_kri_text']=f'{ws.title}!{cell.coordinate}'
   issues.append('Aktual KRI dibaca sebagai teks. Status sumber '+str(status or 'kosong')+' perlu konfirmasi terhadap master; warna lama tidak diwariskan.')
  if 'progress_pelaksanaan_percent' not in proposed:issues.append('Progres Q terpilih kosong; tidak memakai Q sebelumnya.')
 return {'source_reference':f'III.{section}:{r}','source_sheet':'III.'+section,'source_row':r,
  'risk_code':str(value('cause_code') or value('code') or '').strip(),
  'risk_event_text':str(value('title') or '').strip(),'kri_name':str(value('kri_name') or '').strip(),
  'no_risiko':None,'source_risk_sequence':value('code'),'cause':'','proposed_data':proposed,
  'raw_data':{'source_sheet':'III.'+section,'source_row':r,'source_cells':source_cells,'warnings':issues,'errors':errors,'kri_name':str(value('kri_name') or '').strip(),'kri_unit':str(value('kri_unit') or ''),'source_kri_status':str(value('kri_status') or ''),'source_kri_actual':str(value('kri_actual') or ''),'source_risk_sequence':value('code'),'source_rows':[r],'flexible_v1':True,'clear_fields':[k for k,v in proposed.items() if v is None]}}

def combine(group):
 if len(group)==1:return group[0]
 base=group[0];base['raw_data']['source_rows']=[e['source_row'] for e in group]
 base['source_reference']=base['source_reference']+'-'+str(group[-1]['source_row'])
 for k in ['realisasi_rencana_perlakuan','realisasi_output_perlakuan','penjelasan_status_rencana']:
  chunks=[f"{i}. {e['proposed_data'][k]} [baris {e['source_row']}]" for i,e in enumerate(group,1) if e['proposed_data'].get(k)]
  if chunks:base['proposed_data'][k]='\n\n'.join(chunks)
 if len(group)>1:
  base['proposed_data'].pop('persentase_serapan_biaya',None)
 for k in ['realisasi_biaya_perlakuan','progress_pelaksanaan_percent']:
  vals=[Decimal(e['proposed_data'][k]) for e in group if k in e['proposed_data']]
  if len(vals)==len(group):base['proposed_data'][k]=str(sum(vals)/(len(vals) if k=='progress_pelaksanaan_percent' else 1))
  else:base['proposed_data'].pop(k,None);base['raw_data']['warnings'].append(k+' tidak lengkap pada rincian; tidak ditulis.')
 for e in group[1:]:
  base['raw_data']['warnings']+=e['raw_data']['warnings'];base['raw_data']['errors']+=e['raw_data']['errors']
  for k in ['realisasi_pic','realisasi_kri_text']:
   a=base['proposed_data'].get(k);b=e['proposed_data'].get(k)
   if a and b and a!=b:base['raw_data']['errors'].append('Rincian memiliki '+k+' berbeda; perlu dipisahkan/dipetakan manual.')
 base['raw_data']['warnings'].append('Rincian digabung dari baris '+str(base['raw_data']['source_rows']))
 return base

def read_workbook(stream,month,year):
 if month not in range(1,13):raise ValueError('Bulan tidak valid.')
 stream.seek(0)
 with zipfile.ZipFile(stream) as archive:
  if len(archive.infolist())>5000 or sum(info.file_size for info in archive.infolist())>160*1024*1024:raise ValueError('Isi Excel terlalu besar untuk analisis interaktif. Pisahkan file per laporan.')
 stream.seek(0);wb=load_workbook(stream,data_only=True,read_only=False)
 stream.seek(0);fw=load_workbook(stream,data_only=False,read_only=False)
 entries=[];diagnostics={}
 try:
  for section in ['A','B']:
   ws=section_sheet(wb,section);fs=fw[ws.title]
   if ws.max_row*ws.max_column>1500000:raise ValueError('Sheet terlalu besar untuk analisis interaktif.')
   start=anchor(ws);cols,warnings=choose_columns(ws,start,section,month,year)
   if section=='A' and not any(k in cols for k in ['realisasi_nilai_dampak','realisasi_eksposur','realisasi_skor_risiko']):warnings.append('Nilai III.A tidak dapat dibaca secara tunggal. Hanya identitas/kolom yang pasti ditampilkan; nilai risiko tidak ditulis.')
   rows=[];last_identity=None
   for r in range(start,ws.max_row+1):
    identity=[ws.cell(r,cols[k]).value for k in ['code','title','cause_code','kri_name'] if k in cols]
    treatment=ws.cell(r,cols['realisasi_rencana_perlakuan']).value if 'realisasi_rencana_perlakuan' in cols else None
    if section=='A' and not any(identity):
     seq=ws.cell(r,1).value
     if not (isinstance(seq,(int,float)) and seq>0):continue
    if section=='B' and not (any(identity) or treatment):continue
    if any(norm(v) in {'total','jumlah','no risiko','petunjuk','notes'} for v in identity if v):continue
    e=entry(ws,r,section,cols,fs,month)
    if section=='A' and not e['risk_code'] and not e['risk_event_text']:
     if not any(k in e['proposed_data'] for k in ['realisasi_nilai_dampak','realisasi_nilai_probabilitas','realisasi_skor_risiko','realisasi_skala_dampak_id']):continue
     e['raw_data']['item_sequence']=ws.cell(r,1).value;e['raw_data']['warnings'].append('File ringkas tanpa judul/kode risiko; nomor item perlu konfirmasi.')
    if section=='B':
     key=code(e['risk_code']) or norm(e['risk_event_text']) or ('kri:'+norm(e['kri_name']) if e['kri_name'] else '')
     if not key:e['raw_data']['warnings'].append('Identitas risiko tidak tercantum. Pilih target secara manual sebelum impor.');key='row'+str(r)
     e['_group']=key;last_identity=key
    rows.append(e)
   if section=='B':
    groups=[]
    for e in rows:
     if groups and e['_group']==groups[-1][0]['_group']:groups[-1].append(e)
     else:groups.append([e])
    rows=[combine(g) for g in groups]
   for e in rows:e['raw_data']['warnings']+=warnings
   entries+=rows
   diagnostics['III.'+section]={'anchor':f'{ws.title}!A{start}','header_rows':list(range(1,start)),'columns':{k:{'index':v,'letter':get_column_letter(v)} for k,v in cols.items()},'candidate_rows':len(rows),'accepted_rows':len(rows),'skipped_rows':0,'skip_reasons':{},'warnings':warnings,'selected_period':f'{year}-{month:02d}','selected_quarter':f'Q{(month-1)//3+1}'}
  # Cause codes in III.B may be reliable while the merged title cell still says KEU.
  titles={code(e['risk_code']):e['risk_event_text'] for e in entries if e['source_sheet']=='III.A' and e['risk_code'] and e['risk_event_text']}
  for e in entries:
   if e['source_sheet']=='III.B' and code(e['risk_code']) in titles:
    original=e['risk_event_text'];e['risk_event_text']=titles[code(e['risk_code'])]
    if original and norm(original)!=norm(e['risk_event_text']):e['raw_data']['warnings'].append('Judul III.B berbeda; pemetaan memakai kode yang sama dengan III.A. Judul asli: '+original)
  return entries,diagnostics
 finally:wb.close();fw.close();stream.seek(0)
