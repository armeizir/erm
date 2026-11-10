"""Vector procedure diagram, no Graphviz installation or remote renderer."""
from io import BytesIO
from math import atan2,cos,sin,pi
from html import escape
from reportlab.pdfgen import canvas
from reportlab.lib.pagesizes import A4
from reportlab.lib.colors import HexColor, white
from reportlab.platypus import Paragraph
from reportlab.lib.styles import ParagraphStyle
from .flow_service import validate_flow
from pathlib import Path
import reportlab
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
FONT = 'Helvetica'
font_path = Path(reportlab.__file__).resolve().parent / 'fonts' / 'Vera.ttf'
if font_path.is_file():
    if 'SMTFlowSans' not in pdfmetrics.getRegisteredFontNames():
        pdfmetrics.registerFont(TTFont('SMTFlowSans', str(font_path)))
    FONT = 'SMTFlowSans'


BLUE=HexColor('#20556a'); INK=HexColor('#243b49'); PALE=HexColor('#edf5f8')

def paragraph(c,text,x,y,w,size=9,align=0,color=INK,maxheight=100):
    style=ParagraphStyle('flow',fontName=FONT,fontSize=size,leading=size*1.22,alignment=align,textColor=color)
    p=Paragraph(escape(str(text)).replace('\n','<br/>'),style)
    _,h=p.wrap(w,maxheight)
    while h>maxheight and style.fontSize>6.5:
        style.fontSize-=.5;style.leading=style.fontSize*1.22
        p=Paragraph(escape(str(text)).replace('\n','<br/>'),style);_,h=p.wrap(w,maxheight)
    if h>maxheight:raise ValueError('Label terlalu panjang untuk PDF.')
    p.drawOn(c,x,y-h)
    return h

def arrow(c,x1,y1,x2,y2):
    c.setStrokeColor(BLUE);c.setFillColor(BLUE);c.setLineWidth(1)
    c.line(x1,y1,x2,y2);a=atan2(y2-y1,x2-x1);path=c.beginPath();path.moveTo(x2,y2)
    path.lineTo(x2-6*cos(a-pi/7),y2-6*sin(a-pi/7));path.lineTo(x2-6*cos(a+pi/7),y2-6*sin(a+pi/7));path.close();c.drawPath(path,fill=1,stroke=0)

def build_flow_pdf(document,flow,source_hash):
    flow=validate_flow(flow);nodes=flow['nodes'];edges=flow['edges'];pages=(len(nodes)+4)//5
    locations={n['id']:(i//5+1,i%5) for i,n in enumerate(nodes)}
    numbers={n['id']:i+1 for i,n in enumerate(nodes)}
    buf=BytesIO();c=canvas.Canvas(buf,pagesize=A4);c.setTitle('Diagram Alir - '+document.nomor)
    for page in range(1,pages+1):
        c.setFillColor(BLUE);c.rect(0,790,595,52,fill=1,stroke=0)
        paragraph(c,'DIAGRAM ALIR PROSEDUR',28,824,535,size=15,color=white)
        paragraph(c,document.nomor+' | Revisi '+document.revisi,28,783,535,size=10)
        paragraph(c,document.judul,28,765,535,size=10,maxheight=30)
        paragraph(c,'DRAFT AI - PERLU VERIFIKASI',28,727,535,size=10,color=HexColor('#a05114'))
        paragraph(c,'Pelaksana',28,707,103,size=8);paragraph(c,'Kegiatan / keputusan',150,707,245,size=8)
        paragraph(c,'Sambungan',424,707,142,size=8)
        for row,n in enumerate(nodes[(page-1)*5:page*5]):
            cy=645-row*122;cx=272;left=150;right=394;half=35
            c.setStrokeColor(HexColor('#d2e0e7'));c.setFillColor(PALE);c.roundRect(28,cy-31,103,62,5,fill=1,stroke=0)
            paragraph(c,n['actor'],34,cy+22,91,size=8,maxheight=52)
            c.setStrokeColor(BLUE);c.setFillColor(white);c.setLineWidth(1.2)
            if n['kind']=='decision':
                path=c.beginPath();path.moveTo(cx,cy+half+7);path.lineTo(right,cy);path.lineTo(cx,cy-half-7);path.lineTo(left,cy);path.close();c.drawPath(path,fill=1,stroke=1)
                w=135;x=cx-w/2;top=cy+18
            else:
                radius=22 if n['kind'] in {'start','end'} else 5
                c.roundRect(left,cy-half,244,half*2,radius,fill=1,stroke=1)
                w=224;x=left+10;top=cy+22
            paragraph(c,f"#{numbers[n['id']]:02d}  "+n['text'],x,top,w,size=8.5,align=1,maxheight=36 if n['kind']=='decision' else 53)
            outs=[e for e in edges if e['source']==n['id']]
            routes=[]
            for e in outs:
                targetpage,targetrow=locations[e['target']]
                if targetpage==page and targetrow==row+1:
                    y1=cy-half-(7 if n['kind']=='decision' else 0);y2=cy-122+35+(7 if nodes[(page-1)*5+targetrow]['kind']=='decision' else 0)
                    arrow(c,cx,y1,cx,y2)
                    if e['label']:paragraph(c,e['label'],cx+7,(y1+y2)/2+6,50,size=8)
                else:routes.append(e)
            for j,e in enumerate(routes):
                yy=cy+(18 if len(routes)==2 and j==0 else -18 if len(routes)==2 else 0)
                dest=locations[e['target']][0]
                c.setStrokeColor(HexColor('#9ab8c6'));c.setFillColor(PALE);c.roundRect(424,yy-17,142,34,4,fill=1,stroke=1)
                origin=right if n['kind']!='decision' else cx+122*(1-abs(yy-cy)/42)
                arrow(c,origin,yy,420,yy)
                label=(e['label']+' : ' if e['label'] else '')+f"Ke #{numbers[e['target']]:02d} (hal. {dest})"
                paragraph(c,label,429,yy+10,132,size=8,maxheight=28)
        c.setStrokeColor(HexColor('#d2e0e7'));c.line(28,53,567,53)
        paragraph(c,'Kotak sambungan merujuk nomor langkah dan halaman tujuan; termasuk alur balik.',28,45,535,size=7)
        paragraph(c,f'Sumber {source_hash[:12]} | Bukan pengesahan dokumen | Halaman {page}/{pages}',28,30,535,size=7)
        c.showPage()
    if flow['warnings']:
        paragraph(c,'CATATAN UNTUK VERIFIKASI',28,800,535,size=15)
        y=760
        for i,text in enumerate(flow['warnings'],1):y-=paragraph(c,f'{i}. {text}',28,y,535,size=10,maxheight=60)+16
        paragraph(c,'Dihasilkan AI. Periksa pelaksana, kelengkapan langkah, keputusan dan sambungan sebelum digunakan.',28,y-15,535,size=10)
        c.showPage()
    c.save();return buf.getvalue()
