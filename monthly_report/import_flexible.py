"""Django integration for semantic Excel import, without model save() recalculation."""
import hashlib,json,re
from decimal import Decimal,ROUND_HALF_UP
from django.core.exceptions import ValidationError
from django.db import transaction
from django.utils import timezone
from .import_formats import read_workbook,norm,code,month_in


def install(namespace):
 old_analyze=namespace['analyze_import_batch']
 fields=tuple(dict.fromkeys((*namespace['IMPORTABLE_FIELDS'],'realisasi_kri_text','persentase_serapan_biaya')))
 namespace['IMPORTABLE_FIELDS']=fields
 namespace['FIELD_LABELS'].update(realisasi_kri_text='Aktual KRI teks/komposit',realisasi_threshold_kri='Status KRI',realisasi_threshold_kri_skor='Skor/referensi KRI',persentase_serapan_biaya='Serapan biaya (%)')
 def fingerprint(report):
  # Include parent period/status and canonical profile configuration as well as item values.
  state={'report':{f.attname:getattr(report,f.attname) for f in report._meta.concrete_fields},
   'period':str(report.periode.tanggal_mulai),'items':list(report.items.order_by('pk').values()),
   'profiles':list(report.reassessment.item.order_by('pk').values())}
  return hashlib.sha256(json.dumps(state,sort_keys=True,default=str,ensure_ascii=False).encode()).hexdigest()
 def parse(batch,include_diagnostics=False):
  source_months=month_in(batch.original_filename);source_years={int(y) for y in re.findall(r'\b20\d{2}\b',batch.original_filename)}
  period=batch.report.periode.tanggal_mulai
  if (source_months and period.month not in source_months) or (source_years and period.year not in source_years):raise ValidationError('Periode pada nama file berbeda dari laporan tujuan. Pilih laporan/file yang benar.')
  batch.source_file.open('rb')
  try:
   entries,diag=read_workbook(batch.source_file,batch.report.periode.tanggal_mulai.month,batch.report.periode.tanggal_mulai.year)
  except (ValueError,TypeError) as exc:raise ValidationError(str(exc)) from exc
  finally:batch.source_file.close()
  for entry in entries:
   p=entry['proposed_data']
   for key,model in [('realisasi_skala_dampak_id',namespace['MasterSkalaDampak']),('realisasi_skala_probabilitas_id',namespace['MasterSkalaProbabilitas'])]:
    if key in p:
     identity=namespace['_scale_id'](model,p[key])
     if identity is None:entry['raw_data']['errors'].append('Skala tidak ditemukan/aktif: '+str(p[key]))
     else:p[key]=identity
  labels={**namespace['FIELD_LABELS'],'code':'Nomor/kode risiko','title':'Peristiwa risiko','kind':'Jenis risiko','cause_code':'Kode penyebab','kri_name':'Indikator KRI','kri_status':'Status KRI sumber','kri_actual':'Aktual KRI sumber','kri_unit':'Satuan KRI'}
  for diagnostic in diag.values():diagnostic['columns']={labels.get(k,k):v for k,v in diagnostic['columns'].items()}
  return (entries,diag) if include_diagnostics else entries
 def match(report,entry):
  items=list(report.items.select_related('risk_event','risk_event__summary__unit_bisnis'))
  if not items:return None,'target_report_empty',Decimal('0'),[]
  source=entry.get('risk_code','');key=code(source);name=norm(entry.get('risk_event_text'));kri=norm(entry.get('kri_name') or entry.get('raw_data',{}).get('kri_name'))
  # Unit-qualified foreign codes cannot fall back to a common event title.
  own=code(report.reassessment.unit_bisnis.name);short=code(report.reassessment.unit_bisnis.name.split()[-1])
  equivalents={'SETPER':{'SETPER','SEKPER'},'SEKPER':{'SETPER','SEKPER'},'KSPI':{'KSPI','SPI'},'SPI':{'KSPI','SPI'},'KITRAN':{'KITRAN','KITRANS'},'KITRANS':{'KITRAN','KITRANS'}}
  own_units=equivalents.get(short,{short})
  known={'KEU','HCGA','OPS','SETPER','SEKPER','SPI','KSPI','MRK','AGA','RENKIN','BIS','INFRA','KITRAN','KITRANS','DISYAN','BES','MANPRO','K3L','STRADA'}
  source_units={t for t in re.findall(r'[A-Z0-9]+',source.upper()) if t in known}
  if source_units and not source_units.intersection(own_units):return None,'outside_target_profile',Decimal('0'),[]
  start=report.periode.tanggal_mulai;end=report.periode.tanggal_selesai
  valid=[i for i in items if i.risk_event.summary_id==report.reassessment_id and (not i.risk_event.valid_from or i.risk_event.valid_from<=end) and (not i.risk_event.valid_to or i.risk_event.valid_to>=start)]
  if re.search(r'-\s*-',source):return None,'malformed_code',Decimal('0'),[i.pk for i in valid if name and norm(i.risk_event.peristiwa_risiko)==name]
  by_code=[i for i in valid if key and key in namespace['_profile_item_codes'](i.risk_event)]
  by_name=[i for i in valid if name and norm(i.risk_event.peristiwa_risiko)==name]
  if len(by_code)==1:
   if by_name and by_code[0].pk not in {i.pk for i in by_name}:return None,'ambiguous',Decimal('0'),sorted({i.pk for i in by_code+by_name})
   return by_code[0],'exact_code',Decimal('100'),[]
  if len(by_code)>1:return None,'ambiguous',Decimal('0'),[i.pk for i in by_code]
  if len(by_name)==1:return by_name[0],'unique_normalized_name',Decimal('95'),[]
  if len(by_name)>1:return None,'ambiguous',Decimal('0'),[i.pk for i in by_name]
  by_kri=[i for i in valid if kri and norm(i.risk_event.key_risk_indicators)==kri]
  if len(by_kri)==1:return by_kri[0],'unique_kri',Decimal('80'),[]
  if len(by_kri)>1:return None,'ambiguous',Decimal('0'),[i.pk for i in by_kri]
  sequence=entry.get('raw_data',{}).get('item_sequence')
  # Reduced III.A has a Data Item sequence, never treat it as No Risiko.
  by_item=[i for i in valid if sequence is not None and i.risk_event.no_item==sequence]
  if len(by_item)==1:return by_item[0],'item_sequence_review',Decimal('70'),[]
  return None,'unmatched',Decimal('0'),[]
 def validate(entry,item,method,confidence,candidates):
  raw=entry.get('raw_data',{});issues=list(raw.get('warnings',[]));fatal=list(raw.get('errors',[]));p=entry['proposed_data']
  if method=='outside_target_profile':return 'green',['Kode berasal dari bidang/unit lain; baris dilewati.']
  if not item:fatal.append('Tidak ada pemetaan target yang tunggal. Risiko baru harus dibuat melalui alur profil; tidak ditambahkan otomatis. Kandidat: '+str(candidates))
  if method in {'unique_kri','item_sequence_review'}:issues.append('Identitas ringkas dipetakan melalui '+method+'; periksa risiko tujuan sebelum memilih Import.')
  if item and entry.get('risk_event_text') and norm(entry['risk_event_text'])!=norm(item.risk_event.peristiwa_risiko):issues.append('Judul sumber berbeda dengan target. Periksa kecocokan sebelum konfirmasi.')
  for key in ['realisasi_nilai_probabilitas','progress_pelaksanaan_percent']:
   if key in p and p[key] is not None:
    try:
     v=Decimal(str(p[key]));assert v.is_finite() and 0<=v<=100
    except Exception:fatal.append(key+' harus 0–100%.')
  for key in ['realisasi_nilai_dampak','realisasi_eksposur','realisasi_biaya_perlakuan']:
   if key in p and p[key] is not None:
    try:
     v=Decimal(str(p[key]));assert v.is_finite() and v>=0
    except Exception:fatal.append(key+' harus angka tidak negatif.')
  if p.get('realisasi_skor_risiko') is not None and not 1<=int(p['realisasi_skor_risiko'])<=25:fatal.append('Skor risiko harus 1–25.')
  if item:
   if p.get('realisasi_kri_text') and item.realisasi_nilai_kri is None and norm(item.realisasi_kri_text)==norm(p['realisasi_kri_text']):
    p.pop('realisasi_threshold_kri',None);p.pop('realisasi_threshold_kri_skor',None)
    issues.append('Aktual KRI sama dengan data yang ada; status manual yang sudah tersimpan dipertahankan.')
   if p.get('realisasi_pic') and item.realisasi_pic_organization_unit_id:
    issues.append('PIC teks sumber berbeda/tambahan pada mapping organisasi; mapping PIC yang sudah ada dipertahankan.')
    p.pop('realisasi_pic',None)
   qfields=['realisasi_nilai_dampak','realisasi_nilai_probabilitas','realisasi_eksposur']
   if item.risk_event.jenis_risiko=='kuantitatif' and entry.get('source_sheet',raw.get('source_sheet'))=='III.A' and any(k in p for k in qfields) and not all(p.get(k) is not None for k in qfields):fatal.append('Komponen kuantitatif tidak lengkap. Dampak, probabilitas dan eksposur harus tersedia bersama agar tidak bercampur dengan snapshot lama.')
   if item.risk_event.jenis_risiko=='kuantitatif' and all(p.get(k) is not None for k in ['realisasi_nilai_dampak','realisasi_nilai_probabilitas','realisasi_eksposur']):
    expected=(Decimal(str(p['realisasi_nilai_dampak']))*Decimal(str(p['realisasi_nilai_probabilitas']))/100).quantize(Decimal('.01'))
    actual=Decimal(str(p['realisasi_eksposur'])).quantize(Decimal('.01'))
    if expected!=actual:fatal.append('Eksposur sumber tidak sesuai dampak × probabilitas; perbaiki/konfirmasi sumber melalui alur khusus, bukan dihitung ulang diam-diam.')
  if not p:issues.append('Tidak ada nilai periode terpilih untuk diisi. Pilih Lewati.')
  return ('red' if fatal else 'yellow' if issues else 'green'),list(dict.fromkeys(issues+fatal))
 @transaction.atomic
 def analyze(batch):
  if batch.status==batch.STATUS_IMPORTED:raise ValidationError('Batch yang sudah diimpor tidak dapat dianalisis ulang.')
  if batch.report.is_locked:raise ValidationError('Laporan terkunci.')
  return old_analyze(batch)
 @transaction.atomic
 def apply(batch,user):
  from .models import MonthlyRiskReport,MonthlyRiskReportItem,MonthlyRiskReportImportBatch,MonthlyRiskReportSubmissionLog
  batch=MonthlyRiskReportImportBatch.objects.select_for_update().select_related('report__periode','report__reassessment').get(pk=batch.pk)
  report=MonthlyRiskReport.objects.select_for_update().get(pk=batch.report_id)
  if batch.status!=batch.STATUS_REVIEW or report.status not in {'draft','revision'} or report.is_locked:raise ValidationError('Batch/laporan tidak lagi dapat diimpor.')
  if batch.blocking_reason:raise ValidationError(batch.blocking_reason)
  if batch.parser_version!=namespace['IMPORT_PARSER_VERSION'] or batch.target_fingerprint!=fingerprint(report):raise ValidationError('Data laporan/profil berubah sejak pratinjau. Analisis ulang sebelum impor.')
  rows=list(batch.rows.select_for_update().order_by('pk'))
  if any(r.user_decision==r.DECISION_PENDING for r in rows):raise ValidationError('Putuskan setiap baris: Import atau Lewati.')
  selected=[r for r in rows if r.user_decision==r.DECISION_IMPORT]
  if not selected:raise ValidationError('Tidak ada baris yang dipilih untuk diimpor.')
  targets={i.pk:i for i in report.items.select_for_update().select_related('risk_event')}
  merged={};grouped={}
  for row in selected:
   if row.validation_level==row.LEVEL_RED or row.matched_report_item_id not in targets:raise ValidationError('Baris merah/tanpa target tidak dapat diimpor: '+row.source_reference)
   if not row.raw_data.get('flexible_v1'):raise ValidationError('Batch lama perlu dianalisis ulang.')
   item=targets[row.matched_report_item_id]
   entry={'proposed_data':dict(row.proposed_data),'raw_data':row.raw_data,'risk_event_text':row.risk_event_text}
   level,issues=validate(entry,item,row.match_method,row.confidence,[])
   if level=='red':raise ValidationError(issues)
   grouped.setdefault(item.pk,[]).append((row,entry['proposed_data']))
  for pk,records in grouped.items():
   raw_updates,notes=combine_selected(records)
   item=targets[pk];complete_cost_absorption(raw_updates,item);updates={}
   for key,raw_value in raw_updates.items():
    if key not in fields:raise ValidationError('Field tidak diizinkan: '+key)
    field=item._meta.get_field(key[:-3] if key.endswith('_id') else key)
    value=raw_value
    if field.get_internal_type()=='DecimalField' and value is not None:value=Decimal(str(value)).quantize(Decimal(1).scaleb(-field.decimal_places),rounding=ROUND_HALF_UP)
    value=field.clean(value,item)
    updates[key]=value
   merged[pk]=updates
  for pk,updates in merged.items():
   if not updates:continue
   item=targets[pk]
   # A source KRI text requires clearing the previous numeric mode atomically.
   if 'realisasi_kri_text' in updates and updates.get('realisasi_nilai_kri','missing') is not None:raise ValidationError('Mode KRI ganda.')
   previous={k:namespace['_json_value'](getattr(item,k)) for k in updates}
   MonthlyRiskReportItem.objects.filter(pk=pk,report_id=report.pk).update(**updates,updated_at=timezone.now())
   saved=MonthlyRiskReportItem.objects.get(pk=pk)
   for k,v in updates.items():
    if getattr(saved,k)!=v:raise ValidationError('Verifikasi hasil impor gagal: '+k)
   for row in selected:
    if row.matched_report_item_id==pk:
     row.previous_data=previous;row.applied_data={k:namespace['_json_value'](v) for k,v in updates.items()};row.save(update_fields=['previous_data','applied_data','updated_at'])
  namespace['refresh_monthly_report_summary'](report)
  batch.status=batch.STATUS_IMPORTED;batch.imported_by=user;batch.imported_at=timezone.now();batch.save(update_fields=['status','imported_by','imported_at','updated_at'])
  MonthlyRiskReportSubmissionLog.objects.create(report=report,action='import',action_by=user,note='Import terkonfirmasi '+batch.original_filename+'; batch '+str(batch.pk)+'; parser semantik v7.')
  return batch
 namespace.update(_parse_workbook=parse,_match_item=match,_validate_entry=validate,analyze_import_batch=analyze,apply_import_batch=apply,target_item_fingerprint=fingerprint,
  _run_ai_review=lambda batch,rows:(False,'Analisis deterministik berdasarkan header, periode, kode/nama/KRI. Kolom ambigu tidak ditebak. Nilai kosong mempertahankan data lama.'))


def remap_review_row(row,report,raw_target):
 """Persist an explicit reviewer choice, restricted to this report and period."""
 if raw_target is None or not row.raw_data.get('flexible_v1'):return
 if str(row.matched_report_item_id or '')==raw_target:return
 from . import import_services as service
 try:
  if row.match_method=='outside_target_profile':raise ValueError('Sumber berasal dari bidang lain.')
  target=report.items.select_related('risk_event').get(pk=int(raw_target))
  risk=target.risk_event
  if risk.summary_id!=report.reassessment_id or (risk.valid_from and risk.valid_from>report.periode.tanggal_selesai) or (risk.valid_to and risk.valid_to<report.periode.tanggal_mulai):raise ValueError('Periode tidak sesuai.')
 except Exception:
  row.matched_report_item=None;row.validation_level='red';row.issues=['Pilih satu risiko pada laporan dan periode ini.'];row.user_decision='pending'
 else:
  proposed=dict(row.proposed_data)
  level,issues=service._validate_entry({'proposed_data':proposed,'raw_data':row.raw_data,'risk_event_text':row.risk_event_text},target,'manual_mapping',Decimal('100'),[])
  row.matched_report_item=target;row.match_method='manual_mapping';row.confidence=100
  row.validation_level='red' if level=='red' else 'yellow';row.issues=['Pemetaan target dipilih manual oleh reviewer.']+issues
  row.proposed_data=proposed;row.raw_data={**row.raw_data,'manual_target_id':target.pk}
 row.save(update_fields=['matched_report_item','validation_level','issues','user_decision','match_method','confidence','raw_data','proposed_data','updated_at'])


def combine_selected(records):
 """Aggregate only explicitly selected rows, preserving each treatment detail."""
 result={};notes=[];brows=[]
 for row,p in records:
  if row.raw_data.get('source_sheet')=='III.B':brows.append((row,p));continue
  for k,v in p.items():
   if k in result and result[k]!=v:raise ValidationError('Nilai III.A berbeda untuk target sama: '+k)
   result[k]=v
 if not brows:return result,notes
 keys=set().union(*(p.keys() for row,p in brows))
 for key in keys:
  present=[(row,p[key]) for row,p in brows if key in p]
  if key=='persentase_serapan_biaya' and len(brows)>1:continue
  if key in {'realisasi_biaya_perlakuan','progress_pelaksanaan_percent'}:
   if len(present)!=len(brows) or any(v is None for row,v in present):notes.append(key+' tidak lengkap; nilai lama dipertahankan.');continue
   vals=[Decimal(str(v)) for row,v in present];v=sum(vals)/(len(vals) if key=='progress_pelaksanaan_percent' else 1)
   result[key]=str(v.quantize(Decimal('.01'),rounding=ROUND_HALF_UP));continue
  if key in {'realisasi_rencana_perlakuan','realisasi_output_perlakuan','penjelasan_status_rencana'}:
   v='\n\n'.join(str(v)+' ['+row.source_reference+']' for row,v in present) if len(present)>1 else present[0][1]
  elif key=='realisasi_pic':v='; '.join(dict.fromkeys(str(v) for row,v in present))
  else:
   vals={json.dumps(v,sort_keys=True) for row,v in present}
   if len(vals)>1:raise ValidationError('Rincian memiliki '+key+' berbeda. Pisahkan/petakan ulang sebelum impor.')
   v=present[0][1]
  if key in result and result[key]!=v:raise ValidationError('Sumber III.A/III.B bertentangan pada '+key)
  result[key]=v
 return result,notes


def combined_review(rows):
 grouped={};output=[];errors=[]
 for row in rows:
  if row.user_decision=='import' and row.matched_report_item_id:grouped.setdefault(row.matched_report_item_id,[]).append((row,row.proposed_data))
 for pk,records in grouped.items():
  try:values,notes=combine_selected(records)
  except ValidationError as exc:errors.extend(exc.messages);continue
  complete_cost_absorption(values,records[0][0].matched_report_item)
  from .import_services import FIELD_LABELS
  display={FIELD_LABELS.get(k,k):v for k,v in values.items()}
  output.append({'item_id':pk,'target':str(records[0][0].matched_report_item.risk_event),'values':display,'notes':notes})
 return output,errors


def complete_cost_absorption(updates,item):
 if 'realisasi_biaya_perlakuan' not in updates or 'persentase_serapan_biaya' in updates:return
 cost=updates['realisasi_biaya_perlakuan']
 budget=getattr(item,'rencana_biaya_perlakuan',None) or getattr(item.risk_event,'biaya_perlakuan_risiko',None)
 updates['persentase_serapan_biaya']=str((Decimal(str(cost))/Decimal(str(budget))*100).quantize(Decimal('.01'),rounding=ROUND_HALF_UP)) if cost is not None and budget and Decimal(str(budget))>0 else None
