"""科学表达式作为行内项，项后允许软换行；实际PDF仍须核验。"""
from __future__ import annotations
import html
import re
from html.parser import HTMLParser

SCRIPT=r'(?:<(?:sup|sub)\b[^>]*>[^<]+</(?:sup|sub)>)?'
UNIT=r'(?:gCO[₂2]|mAh|GWh|kWh|Wh|mbar|tonne|wt%|°C|kW|Mm|nm|µm|μm|mm|cm|kg|m|g|V|W|h|s|yr|l|L)(?![A-Za-z])(?:[²³])?'+SCRIPT
QUANTITY=r'\d[\d,.]*(?:[–−]\d[\d,.]*)?'+SCRIPT+r'(?:\s*×\s*\d[\d,.]*'+SCRIPT+r')?'
ATOM=re.compile(r'Li<sub\b[^>]*>2</sub>CO<sub\b[^>]*>3</sub>|Li<sub\b[^>]*>6</sub>PS<sub\b[^>]*>5</sub>Cl|(?:US\$|€)?'+QUANTITY+r'(?:\s|&#160;)*'+UNIT+r'(?:(?:\s|&#160;)+'+UNIT+r'){0,2}|US\$(?:\s|&#160;)+'+UNIT+r'(?:(?:\s|&#160;)+'+UNIT+r'){0,2}')

def use_declared_latin_font(value, *, bold_default=False):
    """文字节点中的拉丁字/裸数字使用声明字体，不改HTML属性或布局控制。"""
    class Latin(HTMLParser):
        def __init__(self):super().__init__(convert_charrefs=False);self.parts=[];self.stack=[]
        def handle_starttag(self,tag,attrs):
            self.parts.append(self.get_starttag_text());self.stack.append((tag,dict(attrs).get('style','')))
        def handle_startendtag(self,tag,attrs):self.parts.append(self.get_starttag_text())
        def handle_endtag(self,tag):
            self.parts.append('</'+tag+'>')
            for i in range(len(self.stack)-1,-1,-1):
                if self.stack[i][0]==tag:del self.stack[i:];break
        def handle_data(self,text):
            if any(tag=='style'for tag,_ in self.stack):self.parts.append(text);return
            styled=' '.join(style for _,style in self.stack)
            if re.search(r'font-family:\s*Lat(?:Bold)?\b',styled):self.parts.append(text);return
            family='LatBold'if bold_default or 'SourceBold'in styled else'Lat'
            self.parts.append(re.sub(r'[A-Za-z0-9][A-Za-z0-9.,:/@_$%+=–−×µμ-]*',lambda m:f'<span style="font-family:{family}">{m.group()}</span>',text))
        def handle_entityref(self,name):self.parts.append('&'+name+';')
        def handle_charref(self,name):self.parts.append('&#'+name+';')
    parser=Latin();parser.feed(value);return ''.join(parser.parts)

def keep_scientific_atoms(value, *, bold_prefix=False):
    """使用声明的Lat/LatBold字体；CJK字体的nowrap数字替代字形不可信。"""
    records=[];title_end=value.find('。') if bold_prefix else -1
    def replace(match):
        family='LatBold' if 0<=match.start()<title_end else 'Lat'
        value=match.group()
        visible=html.unescape(re.sub(r'<[^>]+>','',value))
        records.append({'visible_text':visible,'source_measure_visible_text':visible,
                        'font_family':family,'policy':'complete_expression_same_host_line_no_scale',
                        'following_soft_break':'U+200B HTML control; actual visible text must remain identical'})
        # Story的nowrap项与紧邻括注可能粘成更大的词。项后给软断点，
        # 仍由整段实测行排选择是否换行；不会强制产生新印刷行。
        return f'<span style="font-family:{family};white-space:nowrap">{value}</span>&#8203;'
    result=ATOM.sub(replace,value)
    def money(match):
        literal=match.group();digits=re.match(r'US\$[\d,.]+',literal).group()
        records.append({'visible_text':literal,'source_measure_visible_text':literal,'font_family':'Lat+source CJK',
                        'policy':'complete_currency_and_magnitude_same_host_line_no_scale'})
        return '<span style="white-space:nowrap"><span style="font-family:Lat">'+digits+'</span>'+literal[len(digits):]+'</span>&#8203;'
    result=re.sub(r'US\$\d[\d,.]*(?:亿|万)(?:美元)?',money,result)
    def date(match):
        literal=match.group()
        records.append({'visible_text':literal,'source_measure_visible_text':literal,'font_family':'Lat+source CJK',
                        'policy':'source_year_month_same_host_line_no_scale'})
        styled=re.sub(r'\d+',lambda m:'<span style="font-family:Lat">'+m.group()+'</span>',literal)
        return '<span style="white-space:nowrap">'+styled+'</span>&#8203;'
    result=re.sub(r'(?<!\d)\d{4}年(?:\d{1,2}月)?',date,result)
    plain=''.join(html.unescape(re.sub(r'<[^>]+>','',value)).split())
    # 先绑定较长项目，避免“2023年”错误占用“2023年2月”的前缀。
    occupied=[]
    for record in sorted(records,key=lambda r:-len(''.join(r['visible_text'].split()))):
        query=''.join(record['visible_text'].split())
        pos=plain.find(query)
        while pos>=0 and any(pos<b and a<pos+len(query)for a,b in occupied):
            pos=plain.find(query,pos+1)
        if pos<0:raise ValueError('scientific_atom_source_binding')
        record['source_text_offset']=pos;occupied.append((pos,pos+len(query)))
    records.sort(key=lambda r:r['source_text_offset'])
    return result,records
