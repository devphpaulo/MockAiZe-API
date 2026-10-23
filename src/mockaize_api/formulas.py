"""Typed formula interpreter compatible with the studio; never executes source code."""
from __future__ import annotations

import math
import re
import secrets
import unicodedata
import uuid
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal, localcontext
from zoneinfo import ZoneInfo

ALPHA = 'ABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789'
LOCATIONS = dict(zip('AC AL AP AM BA CE DF ES GO MA MT MS MG PA PB PR PE PI RJ RN RS RO RR SC SP SE TO'.split(), ['Rio Branco','Maceió','Macapá','Manaus','Salvador','Fortaleza','Brasília','Vitória','Goiânia','São Luís','Cuiabá','Campo Grande','Belo Horizonte','Belém','João Pessoa','Curitiba','Recife','Teresina','Rio de Janeiro','Natal','Porto Alegre','Porto Velho','Boa Vista','Florianópolis','São Paulo','Aracaju','Palmas']))


def integer(value, minimum, maximum):
    if isinstance(value, bool): raise ValueError('Informe um inteiro válido.')
    n = float(value)
    if not math.isfinite(n) or not n.is_integer() or not minimum <= n <= maximum:
        raise ValueError(f'Informe um inteiro entre {minimum} e {maximum}.')
    return int(n)


def chars(size, alphabet):
    if not alphabet: raise ValueError('Informe os caracteres permitidos.')
    return ''.join(secrets.choice(alphabet) for _ in range(size))


def cnpj_digits(base):
    if not re.fullmatch('[A-Z0-9]{12}', base): raise ValueError('Base CNPJ inválida.')
    def digit(text):
        weights = [5,4,3,2,9,8,7,6,5,4,3,2] if len(text) == 12 else [6,5,4,3,2,9,8,7,6,5,4,3,2]
        remainder = sum((ord(c)-48)*w for c,w in zip(text,weights)) % 11
        return str(0 if remainder < 2 else 11-remainder)
    first = digit(base)
    return first + digit(base+first)


def cpf(mask=False):
    base = chars(9,'0123456789')
    if len(set(base)) == 1: base = base[:8]+('1' if base[0]=='0' else '0')
    for _ in range(2):
        digit = sum(int(c)*(len(base)+1-i) for i,c in enumerate(base))*10 % 11
        base += str(0 if digit == 10 else digit)
    return f'{base[:3]}.{base[3:6]}.{base[6:9]}-{base[9:]}' if mask else base


def valid_cpf(value):
    if not re.fullmatch(r'(?:\d{11}|\d{3}\.\d{3}\.\d{3}-\d{2})',value): return False
    digits=re.sub('[.-]','',value)
    if len(set(digits))==1:return False
    for size in (9,10):
        remainder=sum(int(c)*(size+1-i) for i,c in enumerate(digits[:size]))%11
        if int(digits[size]) != (0 if remainder<2 else 11-remainder):return False
    return True


def cnpj(f):
    establishment=str(f.get('establishment','0001')).upper()
    if not re.fullmatch('[A-Z0-9]{4}' if f.get('mode')=='A' else '[0-9]{4}',establishment) or establishment=='0000':
        raise ValueError('Estabelecimento inválido.')
    root=chars(8,ALPHA if f.get('mode')=='A' else '0123456789')
    while re.fullmatch(r'(\d)\1+',root):root=chars(8,ALPHA if f.get('mode')=='A' else '0123456789')
    result=root+establishment+cnpj_digits(root+establishment)
    return f'{result[:2]}.{result[2:5]}.{result[5:8]}/{result[8:12]}-{result[12:]}' if f.get('mask') else result


def valid_cnpj(value):
    value=value.upper()
    if not re.fullmatch(r'(?:[A-Z0-9]{12}\d{2}|[A-Z0-9]{2}\.[A-Z0-9]{3}\.[A-Z0-9]{3}/[A-Z0-9]{4}-\d{2})',value):return False
    digits=re.sub('[./-]','',value)
    return len(set(digits))>1 and digits[-2:]==cnpj_digits(digits[:12])


def sum_decimals(values):
    texts=[str(value).strip() for value in values]
    if any(len(v)>64 or not re.fullmatch(r'[-+]?\d+(?:\.\d+)?',v) or len(v.partition('.')[2])>12 for v in texts):
        raise ValueError('A soma exige decimais com até 12 casas.')
    with localcontext() as ctx:
        ctx.prec=100
        result=format(sum((Decimal(v) for v in texts),Decimal(0)),'f')
    return result.rstrip('0').rstrip('.') if '.' in result else result


def _slug(value):
    plain=''.join(c for c in unicodedata.normalize('NFD',value) if not unicodedata.combining(c))
    return re.sub('[^a-z0-9]+','.',plain.lower()).strip('.')


def _profile(f,c):
    kind=f['type']; cache=c.setdefault('profiles',{});key=(kind,f.get('group') or 'principal',f.get('state') or 'any')
    if key not in cache:
        if kind=='person':
            first=secrets.choice(['Ana','Marina','Clara','Beatriz','Camila','Luana','Helena','Sofia','Pedro','Lucas','Rafael','Bruno','Thiago','André','Mateus','Daniel'])
            last=secrets.choice(['Almeida','Barbosa','Carvalho','Costa','Ferreira','Lima','Martins','Oliveira','Pereira','Ribeiro','Santos','Souza']);name=first+' '+last
            profile={'name':name,'firstName':first,'lastName':last,'email':_slug(name)+str(secrets.randbelow(9990)+10)+'@example.test'}
        elif kind=='company':
            name=secrets.choice(['Aurora','Horizonte','Ipê','Solar','Atlântica','Nascente','Vereda','Candeia','Brisa','Cedro'])+' '+secrets.choice(['Tecnologia','Serviços','Comércio','Logística','Alimentos','Soluções','Engenharia','Consultoria'])
            profile={'tradeName':name,'legalName':name+' LTDA','email':'contato.'+_slug(name)+str(secrets.randbelow(9990)+10)+'@example.test'}
        else:
            state=f.get('state') or 'any';state=secrets.choice(list(LOCATIONS)) if state=='any' else state
            if state not in LOCATIONS:raise ValueError('UF inválida.')
            street=secrets.choice(['Rua','Avenida','Travessa'])+' '+secrets.choice(['dos Ipês','das Acácias','do Horizonte','das Palmeiras','da Nascente','do Sol','das Flores','da Serra'])
            number=str(secrets.randbelow(2500)+1);district=secrets.choice(['Centro','Jardim Primavera','Vila Nova','Boa Vista','Parque das Flores','Alto da Serra']);zip_code=chars(5,'0123456789')+'-'+chars(3,'0123456789');city=LOCATIONS[state]
            profile={'street':street,'number':number,'district':district,'city':city,'state':state,'zip':zip_code,'full':f'{street}, {number} - {district}, {city}/{state}, {zip_code}'}
        cache[key]=profile
    field=f.get('field') or {'person':'name','company':'legalName','address':'street'}[kind]
    if field not in cache[key]:raise ValueError('Dado de perfil inválido.')
    return cache[key][field]


def _date(f,c):
    zone=ZoneInfo(c.get('timeZone') or 'America/Fortaleza')
    reference=datetime.fromisoformat(c.get('referenceDateTime') or datetime.now(timezone.utc).isoformat()).astimezone(zone)
    value=f.get('value') if f.get('mode')=='specific' else c.get('baseDate')
    if not isinstance(value,str) or not re.fullmatch(r'\d{4}-\d{2}-\d{2}',value):raise ValueError('Informe data AAAA-MM-DD.')
    target=date.fromisoformat(value)
    if f.get('mode')=='offset':target+=timedelta(days=integer(f.get('days',5),-36500,36500))
    if f.get('mode')=='business':
        holidays=set(re.split(r'[\s,;]+',f.get('holidays','')))
        for _ in range(3700):
            target+=timedelta(days=1)
            if target.weekday()<5 and target.isoformat() not in holidays:break
        else:raise ValueError('Não foi encontrado dia útil.')
    instant=datetime.combine(target,reference.timetz(),tzinfo=zone)
    mask=f.get('format') or 'yyyy-MM-dd'
    if mask=='custom':
        custom={'day':True,'month':True,'year':True,'hour':True,'minute':True,'second':True,'order':'DMY','yearDigits':'4','dateSeparator':'/','timeSeparator':':','join':' ','milliseconds':False,'timezone':False,'zone':'app',**f.get('custom',{})}
        names={'D':'day','M':'month','Y':'year'};tokens={'D':'dd','M':'MM','Y':'yy' if custom['yearDigits']=='2' else 'yyyy'}
        d=custom['dateSeparator'].join(tokens[k] for k in custom['order'] if custom[names[k]])
        t=custom['timeSeparator'].join({'hour':'HH','minute':'mm','second':'ss'}[k] for k in ('hour','minute','second') if custom[k])
        if custom['second'] and custom['milliseconds']:t+='.fff'
        if not d and not t:raise ValueError('Selecione um componente de data.')
        mask=d+(("'T'" if custom['join']=='T' else custom['join']) if d and t else '')+t
        if t and custom['timezone']:
            mask+="'Z'" if custom['zone']=='utc' else 'zzz'
            if custom['zone']=='utc':instant=instant.astimezone(timezone.utc)
    offset=instant.strftime('%z');offset=offset[:3]+':'+offset[3:]
    tokens={'yyyy':instant.strftime('%Y'),'yy':instant.strftime('%y'),'MM':instant.strftime('%m'),'dd':instant.strftime('%d'),'HH':instant.strftime('%H'),'mm':instant.strftime('%M'),'ss':instant.strftime('%S'),'fff':f'{instant.microsecond//1000:03}','zzz':offset}
    return re.sub(r"'([^']*)'|yyyy|fff|zzz|yy|MM|dd|HH|mm|ss",lambda m:m.group(1) if m.group(1) is not None else tokens[m.group()],mask)


def evaluate(f,c,depth=0):
    if depth>6 or not isinstance(f,dict):raise ValueError('Fórmula inválida ou composição excede seis níveis.')
    kind=f.get('type')
    if kind=='literal':return str(f.get('value') if f.get('value') is not None else '')
    if kind=='copy':return str(c['sourceValue'](f['path']))
    if kind=='field':return str(c['sourceValue' if f.get('source')=='input' else 'outputValue'](f['path']))
    if kind=='groupSum':return sum_decimals(c['groupValues'](f))
    if kind=='config':return re.sub(r'\s+','',c.get('configName') or 'mock')
    if kind=='count':return str(c.get('count',1))
    if kind=='cpf':return cpf(f.get('mask'))
    if kind=='cnpj':return cnpj(f)
    if kind in ('person','company','address'):return _profile(f,c)
    if kind=='date':return _date(f,c)
    if kind=='list':
        raw=f.get('values',''); values=[str(v).strip() for v in (raw if isinstance(raw,list) else str(raw).splitlines()) if str(v).strip()]
        if not 1<=len(values)<=1000:raise ValueError('Lista exige de 1 a 1000 valores.')
        return secrets.choice(values) if f.get('mode')=='random' else values[integer(f.get('index',0),0,len(values)-1)]
    if kind=='sequence':
        index=c.get('fileIndex',0) if f.get('scope')=='file' else c.get('recordIndex',0)
        value=integer(f.get('start',1),0,999999999)+integer(f.get('step',1),1,999999999)*index
        if value>9007199254740991:raise ValueError('Sequencial excede limite seguro.')
        return str(value).zfill(integer(f.get('width',4),1,30))
    if kind=='zeros':return '0'*integer(f.get('length',8),1,1000)
    if kind=='alpha':return chars(integer(f.get('length',9),1,512),f.get('alphabet') or ALPHA)
    if kind=='hash':return chars(integer(f.get('length',32),1,4096),'ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789' if f.get('format')=='alphanumeric' else '0123456789ABCDEF' if f.get('format')=='HEX' else '0123456789abcdef')
    if kind=='id':
        if f.get('mode')!='common':return str(uuid.uuid4())
        prefix=f.get('prefix') or '';size=integer(f.get('length',12),1,128)
        if len(prefix)>size:raise ValueError('Prefixo excede comprimento total.')
        return prefix+chars(size-len(prefix),ALPHA)
    if kind=='random':
        lo=float(f.get('min',0));hi=float(f.get('max',100));precision=integer(f.get('decimals',2),0,6);factor=10**precision
        if not math.isfinite(lo) or not math.isfinite(hi) or lo>hi:raise ValueError('Intervalo numérico inválido.')
        low=math.ceil(lo*factor);high=math.floor(hi*factor)
        if abs(low)>1e12 or abs(high)>1e12 or not 0<=high-low<=4294967295:raise ValueError('Intervalo aleatório muito grande ou vazio.')
        return f'{(low+secrets.randbelow(high-low+1))/factor:.{precision}f}'
    if kind=='compose':
        parts=f.get('parts',[])
        if not isinstance(parts,list) or not 1<=len(parts)<=100:raise ValueError('Composição exige de 1 a 100 partes.')
        values=[];total=0
        for part in parts:
            result=evaluate(part,c,depth+1);total+=len(result.encode('utf-8'))
            if total>100_000_000:raise ValueError('Composição excede 100 MB.')
            values.append(result)
        return sum_decimals(values) if f.get('operation')=='sum' else (f.get('separator') or '').join(values)
    raise ValueError('Escolha um gerador válido.')


def check_length(value,length,truncate=False):
    text=str(value)
    if length is None or length=='':return text
    size=integer(length,1,4096)
    if truncate:text=text[:size]
    if len(text)!=size:raise ValueError(f'O valor tem {len(text)} caracteres; o campo exige {size}.')
    return text


def filename(value):
    name=str(value or '').strip()
    if not name or re.search(r'[<>:"/\\|?*\x00-\x1f]',name) or name.endswith(('.',' ')) or re.match(r'^(con|prn|aux|nul|com[1-9]|lpt[1-9])(?:\.|$)',name,re.I):raise ValueError('Nome de arquivo inválido ou reservado.')
    if not name.lower().endswith('.xml'):name+='.xml'
    if len(name)>180:raise ValueError('Nome excede 180 caracteres.')
    return name
