"""Namespace aware XML generation, structure validation and return composition."""
from __future__ import annotations

import copy
import json
import re
from datetime import datetime, timezone
from xml.dom import Node, minidom
from xml.parsers.expat import ExpatError
from xml.sax.saxutils import quoteattr

from .errors import ApiError
from .formulas import check_length, evaluate, filename

INPUT_LIMIT = 2_000_000
OUTPUT_LIMIT = 100_000_000
XMLNS = 'http://www.w3.org/2000/xmlns/'
XML_SPACE = 'http://www.w3.org/XML/1998/namespace'


def parse(xml, code='INPUT_XML_INVALID', limit=INPUT_LIMIT):
    if not isinstance(xml,str) or not xml.strip():
        raise ApiError(422,code,'XML ausente ou inválido.')
    if len(xml.encode('utf-8'))>limit:
        if code=='INPUT_XML_INVALID':raise ApiError(413,'INPUT_TOO_LARGE','XML de entrada excede 2 MB.')
        raise ApiError(422,code,'XML salvo excede o limite permitido.')
    if re.search(r'<!\s*(?:DOCTYPE|ENTITY)',xml,re.I):
        raise ApiError(422,code,'DOCTYPE e entidades externas não são aceitos.')
    try:
        doc=minidom.parseString(xml)
        stack=[(doc.documentElement,1)]
        while stack:
            node,depth=stack.pop()
            if depth>128:raise ValueError('Profundidade XML excede 128 níveis.')
            stack.extend((n,depth+1) for n in children(node))
        return doc
    except (ExpatError,ValueError,RecursionError) as exc:
        raise ApiError(422,code,'XML inválido ou profundo demais.') from exc


def children(node):
    return [n for n in node.childNodes if n.nodeType==Node.ELEMENT_NODE]


def identity(node):
    return node.namespaceURI or '',node.localName or node.nodeName


def attributes(node):
    return [a for a in node.attributes.values() if a.namespaceURI!=XMLNS and a.name!='xmlns'] if node.nodeType==Node.ELEMENT_NODE else []


def parts(path):
    value=json.loads(path) if isinstance(path,str) else path
    if not isinstance(value,list) or not value or len(value)>128:raise ValueError('Caminho XML inválido.')
    for i,part in enumerate(value):
        if not isinstance(part,dict) or not isinstance(part.get('name'),str) or not part['name'] or not isinstance(part.get('ns',''),str):raise ValueError('Segmento XML inválido.')
        if part.get('attribute'):
            if i!=len(value)-1:raise ValueError('Atributo deve encerrar caminho.')
        elif isinstance(part.get('index',1),bool) or not isinstance(part.get('index',1),int) or part.get('index',1)<1:raise ValueError('Índice XML inválido.')
    return value


def resolve(doc,path):
    current=doc
    for part in parts(path):
        candidates=attributes(current) if part.get('attribute') else children(current)
        matches=[n for n in candidates if identity(n)==(part.get('ns',''),part['name'])]
        index=0 if part.get('attribute') else part.get('index',1)-1
        if index>=len(matches):return None
        current=matches[index]
    return current


def siblings(node):
    return [n for n in children(node.parentNode) if identity(n)==identity(node)] if node and node.parentNode else []


def records(doc,path):
    node=resolve(doc,path)
    if node is None or node.nodeType!=Node.ELEMENT_NODE:return []
    return siblings(node)


def key(node):
    if node.nodeType==Node.ATTRIBUTE_NODE:return key(node.ownerElement)+[{'ns':node.namespaceURI or '', 'name':node.localName or node.name,'attribute':True}]
    chain=[]
    while node and node.nodeType==Node.ELEMENT_NODE:
        chain.insert(0,{'ns':node.namespaceURI or '', 'name':node.localName or node.tagName,'index':siblings(node).index(node)+1})
        node=node.parentNode
    return chain


def has_prefix(path,prefix):
    return len(path)>=len(prefix) and path[:len(prefix)]==prefix


def reindex(path,group,index):
    value=copy.deepcopy(parts(path));prefix=parts(group)
    if has_prefix(value,prefix):value[len(prefix)-1]['index']=index+1
    return value


def value(node):
    if node is None:raise ValueError('Campo XML não encontrado.')
    if node.nodeType==Node.ATTRIBUTE_NODE:return node.value
    return ''.join(n.data if n.nodeType in (Node.TEXT_NODE,Node.CDATA_SECTION_NODE) else value(n) if n.nodeType==Node.ELEMENT_NODE else '' for n in node.childNodes)


def set_value(node,text):
    text=str(text)
    if node.nodeType==Node.ATTRIBUTE_NODE:node.value=text;return
    text_nodes=[n for n in node.childNodes if n.nodeType in (Node.TEXT_NODE,Node.CDATA_SECTION_NODE)]
    if not text_nodes:node.insertBefore(node.ownerDocument.createTextNode(text),node.firstChild);return
    first=text_nodes[0]
    if first.nodeType==Node.CDATA_SECTION_NODE and ']]>' in text:node.replaceChild(node.ownerDocument.createTextNode(text),first)
    else:first.data=text
    for extra in text_nodes[1:]:node.removeChild(extra)


def connected(doc,node):
    if node is None:return False
    if node.nodeType==Node.ATTRIBUTE_NODE:
        owner=node.ownerElement
        if owner is None or node not in attributes(owner):return False
        node=owner
    while node.parentNode:node=node.parentNode
    return node is doc


def remove(node):
    if node.nodeType==Node.ATTRIBUTE_NODE:node.ownerElement.removeAttributeNode(node)
    else:node.parentNode.removeChild(node)


def all_nodes(doc):
    result=[]
    def walk(node):
        result.append(node);result.extend(attributes(node))
        for child in children(node):walk(child)
    walk(doc.documentElement)
    return result


def _serialize_node(node, depth=0, preserve_space=False):
    if node.nodeType != Node.ELEMENT_NODE:
        return node.toxml()

    space = node.getAttributeNS(XML_SPACE, 'space')
    if space == 'preserve':
        preserve_space = True
    elif space == 'default':
        preserve_space = False

    if preserve_space:
        return node.toxml()

    element_children = [child for child in node.childNodes if child.nodeType == Node.ELEMENT_NODE]
    has_text_content = any(
        child.nodeType == Node.CDATA_SECTION_NODE
        or child.nodeType == Node.TEXT_NODE and child.data.strip()
        for child in node.childNodes
    )
    if not element_children or has_text_content:
        return node.toxml()

    attributes_text = ''.join(
        f' {attribute.name}={quoteattr(attribute.value)}'
        for attribute in node.attributes.values()
    )
    opening_tag = f'<{node.tagName}{attributes_text}>'
    content = [
        child for child in node.childNodes
        if child.nodeType != Node.TEXT_NODE or child.data.strip()
    ]
    lines = [
        '  ' * (depth + 1) + _serialize_node(child, depth + 1, preserve_space)
        for child in content
    ]
    closing_tag = '  ' * depth + f'</{node.tagName}>'
    return opening_tag + '\n' + '\n'.join(lines) + '\n' + closing_tag


def serialize(doc):
    # Normalize indentation-only text between elements while retaining mixed content,
    # CDATA and subtrees marked with xml:space="preserve".
    body='\n'.join(_serialize_node(n) for n in doc.childNodes if n.nodeType!=Node.TEXT_NODE or n.data.strip())
    content=('<?xml version="1.0" encoding="UTF-8"?>\n'+body+'\n').encode('utf-8')
    if len(content)>OUTPUT_LIMIT:raise ApiError(413,'OUTPUT_LIMIT_EXCEEDED','Saída excede 100 MB.')
    # Generated literals may contain XML-invalid control characters.
    parse(content.decode('utf-8'),'CONFIGURATION_INVALID',OUTPUT_LIMIT)
    return content


def signature(node,excluded=None):
    if excluded is not None and node in excluded:return ('RECORD',)
    return (identity(node),tuple(sorted(identity(a) for a in attributes(node))),tuple(signature(n,excluded) for n in children(node)))


def _envelope_signature(doc,group,with_values=False):
    units=records(doc,group);unit_set=set(units)
    def walk(node):
        if node in unit_set:return ('RECORD',)
        sequence=[];marked=False
        for child in children(node):
            if child in unit_set:
                if not marked:sequence.append(('RECORD',));marked=True
            else:sequence.append(walk(child));marked=False
        attribute_values=tuple(sorted((identity(a),a.value if with_values else '') for a in attributes(node)))
        text=''.join(n.data for n in node.childNodes if n.nodeType in (Node.TEXT_NODE,Node.CDATA_SECTION_NODE)).strip() if with_values else ''
        return identity(node),attribute_values,text,tuple(sequence)
    return walk(doc.documentElement)


def validate_return_input(template_xml,group,input_xml):
    template=parse(template_xml,'RETURN_INPUT_TEMPLATE_NOT_READY')
    try:expected=records(template,group)
    except (ValueError,TypeError,KeyError) as exc:raise ApiError(422,'RETURN_INPUT_TEMPLATE_NOT_READY','Unidade de entrada não configurada.') from exc
    if not expected:raise ApiError(422,'RETURN_INPUT_TEMPLATE_NOT_READY','Unidade de entrada não encontrada.')
    doc=parse(input_xml)
    try:actual=records(doc,group)
    except (ValueError,TypeError,KeyError) as exc:raise ApiError(422,'INPUT_XML_STRUCTURE_MISMATCH','Estrutura de entrada divergente.') from exc
    expected_signature=signature(expected[0])
    if not actual or any(signature(n)!=expected_signature for n in expected+actual) or _envelope_signature(template,group)!=_envelope_signature(doc,group):
        raise ApiError(422,'INPUT_XML_STRUCTURE_MISMATCH','Tags, atributos, namespaces ou ordem dos registros divergem do modelo salvo.')
    if len(actual)>500:raise ApiError(422,'RECORD_LIMIT_EXCEEDED','O retorno aceita até 500 registros de entrada.')
    return doc


def _group_values(doc,group_path,field_path,record_path,all_records,read=value):
    group=parts(group_path);field=parts(field_path);record=parts(record_path)
    def compatible_prefix(path,prefix):
        return len(path)>=len(prefix) and all(p.get('ns','')==path[i].get('ns','') and p['name']==path[i]['name'] and (i==len(prefix)-1 or p.get('index',1)==path[i].get('index',1)) for i,p in enumerate(prefix))
    if len(field)<=len(group) or not compatible_prefix(field,group) or group[-1].get('attribute'):raise ValueError('Campo somado precisa estar dentro de um grupo.')
    inside=compatible_prefix(group,record)
    # Every context must visit the same complete record collection for allRecords.
    if all_records:
        if inside:group[len(record)-1]['index']=record[-1].get('index',1)
        if compatible_prefix(field,record):field[len(record)-1]['index']=record[-1].get('index',1)
    if not inside and all_records and compatible_prefix(field,record):
        return [read(resolve(doc,reindex(field,record,i))) for i,_ in enumerate(records(doc,record))]
    def from_group(g,f,single=False):
        first=resolve(doc,g)
        if first is None:return []
        units=[first] if single else siblings(first)
        results=[]
        for unit in units:
            actual=key(unit)+f[len(g):]
            node=resolve(doc,actual)
            if node is None:raise ValueError('Campo ausente em ocorrência do somatório.')
            results.append(read(node))
        return results
    if not inside:return from_group(group,field)
    if not all_records:return from_group(group,field,len(group)==len(record))
    if len(group)==len(record):return from_group(group,field)
    return [v for i,_ in enumerate(records(doc,record)) for v in from_group(reindex(group,record,i),reindex(field,record,i))]


def _replace_records(doc,group,count):
    current=records(doc,group)
    if not current:raise ValueError('Unidade do registro não encontrada.')
    wrapper=[]
    if current[0] is doc.documentElement and count>1:
        root=current[0];container=doc.createElement('MockRegistros');doc.replaceChild(container,root);container.appendChild(root);wrapper=key(container)
    first=current[0];parent=first.parentNode;next_node=current[-1].nextSibling;template=first.cloneNode(True)
    for node in current:parent.removeChild(node)
    inserted=[]
    for _ in range(count):
        node=template.cloneNode(True);parent.insertBefore(node,next_node);inserted.append(node)
    return key(inserted[0]),wrapper


def _generate(config,mode,count,source_xml,input_group,template_xml,output_group,rules,presence,headers,name_formula,file_index):
    source=parse(source_xml,'CONFIGURATION_INVALID');template=parse(template_xml,'CONFIGURATION_INVALID')
    units=records(template,output_group)
    if not units:raise ValueError('Unidade de saída não encontrada.')
    for header_path in headers:
        header=resolve(template,header_path)
        if header is None or header.nodeType!=Node.ELEMENT_NODE or len(records(template,header_path))!=1 or has_prefix(parts(header_path),parts(output_group)) or has_prefix(parts(output_group),parts(header_path)):
            raise ValueError('Cabeçalho deve ser único e externo à unidade repetida.')
    original=template.cloneNode(True)
    for node in records(original,output_group)[1:]:remove(node)
    original_nodes=[(key(n), n.nodeType==Node.ATTRIBUTE_NODE or not children(n)) for n in all_nodes(original)]
    for path,rule in rules.items():
        if not isinstance(rule,dict):raise ValueError('Regra de campo inválida.')
        if resolve(template,path) is None:raise ValueError('Regra sem campo: '+path)
    for path,policy in presence.items():
        if resolve(template,path) is None:raise ValueError('Presença sem campo: '+path)
        if policy.get('requirement')=='optional' and (policy.get('include') is False or policy.get('distribution')=='alternate') and has_prefix(parts(output_group),parts(path)):
            raise ValueError('Raiz e caminho da unidade devem permanecer presentes.')
    estimated=len(template_xml.encode('utf-8'))+len(units[0].toxml().encode('utf-8'))*count
    if estimated>OUTPUT_LIMIT:raise ApiError(413,'OUTPUT_LIMIT_EXCEEDED','Saída estimada excede 100 MB.')
    doc=template.cloneNode(True);actual_group,wrapper=_replace_records(doc,output_group,count)
    def actual(path,index=0):return reindex(wrapper+parts(path),actual_group,index)
    context={'referenceDateTime':config.get('referenceDateTime') or datetime.now(timezone.utc).isoformat(),'timeZone':config.get('timeZone') or 'America/Fortaleza','baseDate':config.get('baseDate'),'configName':config.get('name','mock'),'fileIndex':file_index,'count':count}
    jobs={};policies=[];evaluated_bytes=0
    def evaluate_target(target):
        nonlocal evaluated_bytes
        if not connected(doc,target):raise ValueError('Campo de saída ausente ou omitido.')
        if target not in jobs:return value(target)
        job=jobs[target]
        if job['status']=='done':return job['value']
        if job['status']=='visiting':raise ValueError('Dependência circular entre fórmulas.')
        job['status']='visiting';rule=job['rule'];ctx=job['context']
        if rule.get('lengthTarget')=='input' and rule.get('exactLength') is not None:
            ctx={**ctx,'sourceValue':lambda p:check_length(job['context']['sourceValue'](p),rule['exactLength'],True),'groupValues':lambda f:[check_length(v,rule['exactLength'],True) for v in job['context']['groupValues'](f)] if f.get('source')=='input' else job['context']['groupValues'](f)}
        result=str(rule['fixed']) if rule.get('fixed') is not None else evaluate(rule['generator'],ctx) if rule.get('generator') else value(target)
        if rule.get('lengthTarget')!='input':result=check_length(result,rule.get('exactLength'),rule.get('lengthTarget')=='output')
        evaluated_bytes+=len(result.encode('utf-8'))
        if evaluated_bytes>OUTPUT_LIMIT:raise ApiError(413,'OUTPUT_LIMIT_EXCEEDED','Valores gerados excedem 100 MB.')
        set_value(target,result);job.update(status='done',value=result)
        return result
    # All jobs are registered before evaluation so forward references and all-record sums work.
    for index in range(count):
        source_index=index if mode=='return' else 0
        def make_context(index,source_index):
            return {**context,'recordIndex':index,'profiles':{},'sourceValue':lambda p:value(resolve(source,reindex(p,input_group,source_index))),'outputValue':lambda p:evaluate_target(resolve(doc,actual(p,index))),'groupValues':lambda f:_group_values(source,reindex(f['group'],input_group,source_index),reindex(f['path'],input_group,source_index),input_group,f.get('allRecords',False)) if f.get('source')=='input' else _group_values(doc,actual(f['group'],index),actual(f['path'],index),actual_group,f.get('allRecords',False),evaluate_target)}
        ctx=make_context(index,source_index)
        refs=[(path,is_field,resolve(doc,actual(path,index))) for path,is_field in original_nodes if index==0 or has_prefix(path,parts(output_group))]
        for path,is_field,target in refs:
            policy=presence.get(json.dumps(path,separators=(',',':')))
            if policy is None:policy=next((p for k,p in presence.items() if parts(k)==path),None)
            if policy:
                policies.append((policy,is_field,target))
                if policy.get('requirement')=='optional' and (policy.get('include') is False or policy.get('distribution')=='alternate' and index%2==1) and connected(doc,target):remove(target)
        for path,is_field,target in refs:
            if not is_field or not connected(doc,target):continue
            rule=next((rule for k,rule in rules.items() if parts(k)==path),None)
            if rule and (rule.get('generator') or rule.get('fixed') is not None or rule.get('exactLength') is not None):jobs[target]={'rule':rule,'context':ctx,'status':'pending'}
    for target in jobs:
        if connected(doc,target):evaluate_target(target)
    for policy,is_field,target in policies:
        if policy.get('requirement')=='required' and is_field and connected(doc,target) and not value(target).strip():raise ValueError('Campo obrigatório sem valor.')
    for path in headers:
        if len(records(doc,actual(path)))!=1:raise ValueError('Cabeçalho precisa permanecer único na saída.')
    naming={**context,'recordIndex':0,'profiles':{},'sourceValue':lambda p:value(resolve(source,p)),'outputValue':lambda p:value(resolve(doc,actual(p))),'groupValues':lambda f:_group_values(source,f['group'],f['path'],input_group,f.get('allRecords',False)) if f.get('source')=='input' else _group_values(doc,actual(f['group']),actual(f['path']),actual_group,f.get('allRecords',False))}
    return {'content':serialize(doc),'fileName':filename(evaluate(name_formula,naming)),'records':count},doc,actual_group


def _input(config,mode):
    saved=config.get('inputByMode',{}).get(mode,{})
    return saved.get('xml') or '',saved.get('group') or ''


def generate_new(variation,record_count,file_index=0):
    if isinstance(record_count,bool) or not isinstance(record_count,int) or not 1<=record_count<=500:raise ApiError(422,'VALIDATION_ERROR','recordCount deve ser um inteiro entre 1 e 500.')
    try:
        config=copy.deepcopy(variation['config']);config['name']=variation.get('name','mock');source,group=_input(config,'new')
        if not source or not group:raise ApiError(422,'NEW_TEMPLATE_NOT_READY','Modelo de Novo não está pronto.')
        result,_,_=_generate(config,'new',record_count,source,group,source,group,config.get('rulesByMode',{}).get('new',{}),config.get('presenceByMode',{}).get('new',{}),config.get('headersByMode',{}).get('new',[]),config.get('filenameByMode',{}).get('new') or {'type':'literal','value':config.get('fileName','mock')},file_index)
        return [result]
    except ApiError:raise
    except (ValueError,TypeError,KeyError,AttributeError,OverflowError,RecursionError) as exc:raise ApiError(422,'CONFIGURATION_INVALID','Configuração de geração inválida. Revise os modelos, caminhos e fórmulas salvos.') from exc


def _select(config,selection):
    models=config.get('returnModels',[])
    if not isinstance(selection,dict):raise ValueError('Seleção de retorno inválida.')
    if selection.get('type')=='all':selected=models
    elif selection.get('type')=='ids':
        ids=selection.get('ids')
        if not isinstance(ids,list) or not ids or not all(isinstance(i,str) for i in ids) or len(ids)!=len(set(ids)):raise ValueError('Seleção exige IDs distintos.')
        indexed={m['id']:m for m in models}
        if any(i not in indexed for i in ids):raise ApiError(404,'RETURN_NOT_FOUND','Modelo de retorno não encontrado neste arquivo.')
        selected=[indexed[i] for i in ids]
    else:raise ValueError('Tipo de seleção inválido.')
    if not selected:raise ApiError(422,'RETURN_NOT_READY','Nenhum modelo de retorno salvo.')
    if len(selected)>20:raise ValueError('Selecione até 20 modelos.')
    for model in selected:
        if not model.get('outputXml') or not model.get('outputGroup'):raise ApiError(422,'RETURN_NOT_READY','Modelo de retorno incompleto.',returnId=model.get('id'))
    return selected


def generate_return(variation,selection,composition='apart',input_xml=None,file_index=0):
    try:
        if composition not in ('apart','mixed'):raise ValueError('Composição inválida.')
        config=copy.deepcopy(variation['config']);config['name']=variation.get('name','mock');template,group=_input(config,'return')
        if not template or not group:raise ApiError(422,'RETURN_INPUT_TEMPLATE_NOT_READY','Modelo de entrada de Retorno não está pronto.')
        source=template if input_xml is None else input_xml;doc=validate_return_input(template,group,source);count=len(records(doc,group));selected=_select(config,selection)
        generated=[];total=0
        for model in selected:
            item,output,output_group=_generate(config,'return',count,source,group,model['outputXml'],model['outputGroup'],model.get('rules',{}),model.get('presence',{}),model.get('headers',[]),model.get('filename') or {'type':'literal','value':model['name']},file_index)
            item.update(returnId=model['id'],returnName=model['name']);generated.append((item,output,output_group));total+=len(item['content'])
            if total>OUTPUT_LIMIT:raise ApiError(413,'OUTPUT_LIMIT_EXCEEDED','Saída total excede 100 MB.')
        if composition=='apart':return [item for item,_,_ in generated]
        first,base,base_group=generated[0];base_units=records(base,base_group)
        envelope=_envelope_signature(base,base_group,True);record_signatures=[signature(n) for n in base_units]
        for _,output,output_group in generated:
            if parts(output_group)!=parts(base_group) or _envelope_signature(output,output_group,True)!=envelope or [signature(n) for n in records(output,output_group)]!=record_signatures:
                raise ApiError(422,'RETURN_MODELS_INCOMPATIBLE','Modelos exigem o mesmo envelope, cabeçalho, caminho e estrutura de registros.')
        if len(generated)>1:
            parent=base_units[0].parentNode
            # A root record cannot be interleaved without inventing an envelope.
            if parent.nodeType==Node.DOCUMENT_NODE:raise ApiError(422,'RETURN_MODELS_INCOMPATIBLE','Modelos não possuem envelope para intercalar registros.')
            next_node=base_units[-1].nextSibling
            collections=[records(output,output_group) for _,output,output_group in generated]
            for node in base_units:parent.removeChild(node)
            for index in range(count):
                for units in collections:
                    imported=base.importNode(units[index],True)
                    # Namespace declarations on the source envelope are outside
                    # the cloned subtree. Materialize the in-scope bindings.
                    bindings={};ancestor=units[index]
                    while ancestor and ancestor.nodeType==Node.ELEMENT_NODE:
                        for attribute in ancestor.attributes.values():
                            if attribute.namespaceURI==XMLNS or attribute.name=='xmlns':bindings.setdefault(attribute.name,attribute.value)
                        ancestor=ancestor.parentNode
                    bindings.setdefault('xmlns','')
                    for name,uri in bindings.items():imported.setAttributeNS(XMLNS,name,uri)
                    parent.insertBefore(imported,next_node)
        return [{ 'content':serialize(base),'fileName':first['fileName'],'records':count*len(generated)}]
    except ApiError:raise
    except (ValueError,TypeError,KeyError,AttributeError,OverflowError,RecursionError) as exc:raise ApiError(422,'CONFIGURATION_INVALID','Configuração de geração inválida. Revise os modelos, caminhos e fórmulas salvos.') from exc
