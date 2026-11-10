"""Use PRISMA's existing runtime AI configuration for procedure diagrams."""
import json
import socket
from urllib import request, error
from urllib.parse import quote
from .ai_service import prisma_ai_settings, AIReviewError, NoRedirect

def request_flow(source, schema, instructions):
    options = prisma_ai_settings()
    key, model = options['key'], options['model']
    payload = {'model': model, 'store': False, 'max_output_tokens': 6000,
        'instructions': instructions,
        'input': json.dumps(source, ensure_ascii=False),
        'text': {'format': {'type': 'json_schema', 'name': 'smt_procedure_flow', 'strict': True, 'schema': schema}}}
    if options['provider'] == 'gemini':
        endpoint = options['base'] + '/models/' + quote(model.removeprefix('models/'), safe='') + ':generateContent'
        headers = {'x-goog-api-key': key, 'Content-Type': 'application/json'}
        payload = {'systemInstruction': {'parts': [{'text': payload['instructions'] +
            ' Kembalikan hanya JSON yang memenuhi skema ini: ' + json.dumps(schema)}]},
            'contents': [{'role': 'user', 'parts': [{'text': payload['input']}]}],
            'generationConfig': {'responseMimeType': 'application/json',
                'temperature': options['temperature'], 'maxOutputTokens': 6000}}
    else:
        # 'other' explicitly uses the OpenAI Responses-compatible wire format.
        endpoint = options['base'] + '/responses'
        headers = {'Authorization': 'Bearer ' + key, 'Content-Type': 'application/json'}
        if model.startswith(('gpt-4', 'chatgpt-4')):
            payload['temperature'] = options['temperature']
    req = request.Request(endpoint, data=json.dumps(payload).encode(), headers=headers, method='POST')
    try:
        with request.build_opener(NoRedirect()).open(req, timeout=30) as response:
            raw = response.read(1024*1024+1)
        if len(raw) > 1024*1024:raise AIReviewError('Respons AI terlalu besar.')
        data = json.loads(raw)
        if options['provider'] == 'gemini':
            candidates = data.get('candidates', [])
            if not candidates or candidates[0].get('finishReason') != 'STOP':
                raise AIReviewError('Pemeriksaan AI belum selesai atau ditolak provider. Coba bagian yang lebih pendek.')
            texts = [part['text'] for part in candidates[0].get('content', {}).get('parts', []) if 'text' in part]
        else:
            if data.get('status') != 'completed':raise AIReviewError('Pemeriksaan AI belum selesai. Coba bagian yang lebih pendek.')
            texts = [part['text'] for message in data.get('output', []) if message.get('type') == 'message'
                     for part in message.get('content', []) if part.get('type') == 'output_text']
        result = json.loads(''.join(texts))
        return result
    except error.HTTPError as exc:
        if exc.code in {401, 403}:raise AIReviewError('Akses API ditolak. Periksa konfigurasi key dan model.') from None
        if exc.code == 429:raise AIReviewError('Batas penggunaan API tercapai. Periksa kuota atau coba lagi nanti.') from None
        raise AIReviewError('Layanan AI tidak tersedia. Tidak ada perubahan dokumen.') from None
    except (error.URLError, socket.timeout, TimeoutError, OSError):
        raise AIReviewError('Koneksi AI gagal atau melewati batas waktu. Tidak ada perubahan dokumen.') from None
    except (ValueError, KeyError, TypeError, AttributeError):
        raise AIReviewError('Respons AI tidak valid. Tidak ada perubahan dokumen.') from None
