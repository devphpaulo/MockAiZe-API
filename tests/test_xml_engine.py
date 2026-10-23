import json
import unittest
from xml.dom import minidom
from mockaize_api.errors import ApiError
from mockaize_api.xml_engine import generate_new, generate_return, validate_return_input


def path(*names):
    return json.dumps([{'ns': '', 'name': name, 'index': 1} for name in names])


def variation():
    return {'name': 'Test Config', 'config': {
        'inputByMode': {'new': {'xml': '<root><header>H</header><r><a>1</a><b>2</b></r></root>', 'group': path('root', 'r')},
                        'return': {'xml': '<root><r><a>1</a></r></root>', 'group': path('root', 'r')}},
        'filenameByMode': {'new': {'type': 'literal', 'value': 'new'}},
        'rulesByMode': {'new': {path('root', 'r', 'a'): {'generator': {'type': 'sequence', 'width': 2}}}},
        'returnModels': [{'id': 'A', 'name': 'Aceito', 'outputXml': '<out><r><a>A</a></r></out>',
                          'outputGroup': path('out', 'r'), 'rules': {path('out', 'r', 'a'): {'generator': {'type': 'copy', 'path': path('root', 'r', 'a')}}},
                          'filename': {'type': 'literal', 'value': 'return'}, 'headers': [], 'presence': {}}]}}


class EngineTests(unittest.TestCase):
    def test_new_uses_requested_count_and_preserves_header(self):
        result = generate_new(variation(), 3)[0]
        doc = minidom.parseString(result['content'])
        self.assertEqual(['01', '02', '03'], [n.firstChild.data for n in doc.getElementsByTagName('a')])
        self.assertEqual(1, len(doc.getElementsByTagName('header')))
        self.assertEqual('new.xml', result['fileName'])

    def test_return_copies_each_input_record(self):
        result = generate_return(variation(), {'type': 'all'}, input_xml='<root><r><a>9</a></r><r><a>8</a></r></root>')[0]
        self.assertEqual(2, result['records'])
        self.assertIn(b'<a>8</a>', result['content'])

    def test_second_divergent_record_is_rejected(self):
        with self.assertRaises(ApiError) as caught:
            validate_return_input('<root><r><a>1</a></r></root>', path('root', 'r'), '<root><r><a>1</a></r><r><b>2</b></r></root>')
        self.assertEqual('INPUT_XML_STRUCTURE_MISMATCH', caught.exception.code)

    def test_dtd_is_rejected(self):
        with self.assertRaises(ApiError):
            validate_return_input('<r/>', path('r'), '<!DOCTYPE r [<!ENTITY a "a">]><r>&a;</r>')

    def test_cycle_is_controlled(self):
        v = variation()
        v['config']['rulesByMode']['new'] = {path('root','r',name): {'generator': {'type': 'field','path': path('root','r',other)}} for name, other in [('a','b'),('b','a')]}
        with self.assertRaises(ApiError): generate_new(v, 1)

    def test_mixed_interleaves_models(self):
        import copy
        v = variation()
        second = copy.deepcopy(v['config']['returnModels'][0])
        second.update(id='B', name='Recusado', rules={path('out','r','a'): {'fixed': 'B'}})
        v['config']['returnModels'].append(second)
        content = generate_return(v, {'type': 'all'}, 'mixed', '<root><r><a>1</a></r><r><a>2</a></r></root>')[0]['content']
        doc = minidom.parseString(content)
        self.assertEqual(['1','B','2','B'], [n.firstChild.data for n in doc.getElementsByTagName('a')])

    def test_mixed_rejects_incompatible_envelope(self):
        import copy
        v=variation(); model=copy.deepcopy(v['config']['returnModels'][0]); model.update(id='B',rules={},outputXml='<different><r><a>A</a></r></different>',outputGroup=path('different','r'));v['config']['returnModels'].append(model)
        with self.assertRaises(ApiError) as caught: generate_return(v, {'type':'all'}, 'mixed')
        self.assertEqual('RETURN_MODELS_INCOMPATIBLE',caught.exception.code)

    def test_new_count_limits_include_500_and_reject_boolean(self):
        self.assertEqual(500, len(minidom.parseString(generate_new(variation(),500)[0]['content']).getElementsByTagName('r')))
        for count in (0,501,True,1.1,'2'):
            with self.subTest(count=count), self.assertRaises(ApiError): generate_new(variation(),count)

    def test_namespace_prefix_is_irrelevant_but_uri_and_attribute_set_matter(self):
        group=json.dumps([{'ns':'urn:t','name':'root','index':1},{'ns':'urn:t','name':'r','index':1}])
        template='<s:root xmlns:s="urn:t"><s:r id="1"><s:a>1</s:a></s:r></s:root>'
        validate_return_input(template,group,'<x:root xmlns:x="urn:t"><x:r id="2"><x:a>changed</x:a></x:r></x:root>')
        for xml in ['<root><r id="1"><a>1</a></r></root>','<s:root xmlns:s="urn:t"><s:r><s:a>1</s:a></s:r></s:root>']:
            with self.subTest(xml=xml),self.assertRaises(ApiError):validate_return_input(template,group,xml)

    def test_structure_checks_order_attributes_each_record_and_envelope(self):
        template='<root><h x="1" y="2"/><r><a/><b/></r><end/></root>'
        validate_return_input(template,path('root','r'),'<root><h y="9" x="8"/><!-- ignored --><r><a>value</a><b/></r><r><a/><b/></r><end/></root>')
        for xml in ['<root><h x="1" y="2"/><r><b/><a/></r><end/></root>', '<root><h x="1" y="2"/><r><a/><b/></r><r><a/><b z="1"/></r><end/></root>', '<root><h x="1" y="2"/><r><a/><b/></r></root>']:
            with self.subTest(xml=xml),self.assertRaises(ApiError):validate_return_input(template,path('root','r'),xml)

    def test_namespaced_attribute_and_second_sibling_path(self):
        v=variation();group=json.dumps([{'ns':'urn:t','name':'root','index':1},{'ns':'urn:t','name':'r','index':1}])
        v['config']['inputByMode']['new']={'xml':'<t:root xmlns:t="urn:t"><t:r t:id="old"><t:a>first</t:a><t:a><![CDATA[second]]></t:a></t:r></t:root>','group':group}
        attribute=json.dumps(json.loads(group)+[{'ns':'urn:t','name':'id','attribute':True}]);second=json.dumps(json.loads(group)+[{'ns':'urn:t','name':'a','index':2}])
        v['config']['rulesByMode']['new']={attribute:{'generator':{'type':'sequence','width':1}},second:{'fixed':']]> & café'}}
        doc=minidom.parseString(generate_new(v,2)[0]['content'])
        self.assertEqual(['1','2'],[n.getAttributeNS('urn:t','id') for n in doc.getElementsByTagNameNS('urn:t','r')])
        self.assertEqual(']]> & café',doc.getElementsByTagNameNS('urn:t','a')[3].firstChild.data)

    def test_forward_reference_and_global_decimal_sum(self):
        v=variation();v['config']['inputByMode']['new']['xml']='<root><total/><r><a>0</a><b>0</b></r></root>'
        v['config']['rulesByMode']['new']={path('root','total'):{'generator':{'type':'groupSum','source':'output','group':path('root','r'),'path':path('root','r','b'),'allRecords':True}},path('root','r','a'):{'generator':{'type':'field','source':'output','path':path('root','r','b')}},path('root','r','b'):{'generator':{'type':'random','min':0.1,'max':0.1,'decimals':1}}}
        content=generate_new(v,3)[0]['content']
        self.assertIn(b'<total>0.3</total>',content);self.assertEqual(3,content.count(b'<a>0.1</a>'))

    def test_nested_group_sum_per_record_and_all_input_records(self):
        v=variation();group=path('root','r');item=path('root','r','item');field=path('root','r','item','a')
        xml='<root><r><item><a>0.1</a></item><item><a>0.2</a></item></r><r><item><a>0.3</a></item><item><a>0.4</a></item></r></root>'
        v['config']['inputByMode']['return']={'xml':xml,'group':group}
        model=v['config']['returnModels'][0];model['rules']={path('out','r','a'):{'generator':{'type':'groupSum','source':'input','group':item,'path':field}}}
        content=generate_return(v,{'type':'all'})[0]['content'];self.assertIn(b'<a>0.3</a>',content);self.assertIn(b'<a>0.7</a>',content)
        model['rules'][path('out','r','a')]['generator']['allRecords']=True
        content=generate_return(v,{'type':'all'})[0]['content'];self.assertEqual(2,content.count(b'<a>1</a>'))

    def test_optional_alternate_and_required_empty(self):
        v=variation();v['config']['presenceByMode']={'new':{path('root','r','b'):{'requirement':'optional','include':True,'distribution':'alternate'}}}
        doc=minidom.parseString(generate_new(v,3)[0]['content']);self.assertEqual([1,0,1],[len(n.getElementsByTagName('b')) for n in doc.getElementsByTagName('r')])
        v['config']['rulesByMode']['new'][path('root','r','b')]={'fixed':''}
        v['config']['presenceByMode']['new'][path('root','r','b')]={'requirement':'required','include':True,'distribution':'all'}
        with self.assertRaises(ApiError):generate_new(v,1)

    def test_length_validate_input_and_output(self):
        v=variation();v['config']['rulesByMode']['new']={path('root','r','a'):{'fixed':'é😀abc','exactLength':2,'lengthTarget':'output'}}
        content=generate_new(v,1)[0]['content'];self.assertIn('<a>é😀</a>'.encode(),content)
        rule=v['config']['rulesByMode']['new'][path('root','r','a')];rule['lengthTarget']='validate'
        with self.assertRaises(ApiError):generate_new(v,1)
        rule.update(generator={'type':'copy','path':path('root','r','b')},fixed=None,exactLength=1,lengthTarget='input')
        self.assertIn(b'<a>2</a>',generate_new(v,1)[0]['content'])

    def test_orphan_rule_omitted_dependency_header_and_invalid_character_fail(self):
        v=variation();v['config']['rulesByMode']['new'][path('root','missing')]={'fixed':'x'}
        with self.assertRaises(ApiError):generate_new(v,1)
        v=variation();v['config']['headersByMode']={'new':[path('root','r')]}
        with self.assertRaises(ApiError):generate_new(v,1)
        v=variation();v['config']['rulesByMode']['new'][path('root','r','a')]={'fixed':'\x01'}
        with self.assertRaises(ApiError):generate_new(v,1)
        v=variation();v['config']['presenceByMode']={'new':{path('root','r','b'):{'requirement':'optional','include':False,'distribution':'all'}}};v['config']['rulesByMode']['new'][path('root','r','a')]={'generator':{'type':'field','path':path('root','r','b')}}
        with self.assertRaises(ApiError):generate_new(v,1)

    def test_root_unit_gets_studio_wrapper_for_multiple_new_records(self):
        v=variation();v['config']['inputByMode']['new']={'xml':'<r><a>1</a></r>','group':path('r')};v['config']['rulesByMode']['new']={path('r','a'):{'generator':{'type':'sequence'}}}
        doc=minidom.parseString(generate_new(v,2)[0]['content']);self.assertEqual('MockRegistros',doc.documentElement.tagName);self.assertEqual(2,len(doc.getElementsByTagName('r')))

    def test_selection_duplicates_unknown_and_incomplete_fail(self):
        for selection in [{'type':'ids','ids':['A','A']},{'type':'ids','ids':['B']},{'type':'ids','ids':[]}]:
            with self.subTest(selection=selection),self.assertRaises(ApiError):generate_return(variation(),selection)
        v=variation();v['config']['returnModels'][0]['outputXml']=''
        with self.assertRaises(ApiError):generate_return(v,{'type':'all'})

    def test_input_byte_size_depth_and_invalid_xml_fail(self):
        for xml in ['<root>','<root>'+('é'*1_000_000)+'</root>','<a>'*130+'</a>'*130]:
            with self.subTest(size=len(xml)),self.assertRaises(ApiError):validate_return_input('<root><r><a/></r></root>',path('root','r'),xml)

    def test_output_limit_applies_before_publication(self):
        from unittest.mock import patch
        with patch('mockaize_api.xml_engine.OUTPUT_LIMIT',100):
            with self.assertRaises(ApiError) as caught:generate_new(variation(),10)
            self.assertEqual('OUTPUT_LIMIT_EXCEEDED',caught.exception.code)

    def test_selected_order_overrides_saved_order(self):
        import copy
        v=variation();model=copy.deepcopy(v['config']['returnModels'][0]);model.update(id='B',name='B');v['config']['returnModels'].append(model)
        self.assertEqual(['B','A'],[i['returnId'] for i in generate_return(v,{'type':'ids','ids':['B','A']})])

    def test_mixed_rejects_different_header_value_and_record_shape(self):
        import copy
        for output in ['<out><h>B</h><r><a>A</a></r></out>','<out><h>A</h><r><b>A</b></r></out>']:
            v=variation();first=v['config']['returnModels'][0];first['outputXml']='<out><h>A</h><r><a>A</a></r></out>'
            second=copy.deepcopy(first);second.update(id='B',rules={},outputXml=output);v['config']['returnModels'].append(second)
            with self.subTest(output=output),self.assertRaises(ApiError) as caught:generate_return(v,{'type':'all'},'mixed')
            self.assertEqual('RETURN_MODELS_INCOMPATIBLE',caught.exception.code)

    def test_record_count_cannot_move_units_across_footer(self):
        with self.assertRaises(ApiError):validate_return_input('<root><r><a/></r><footer/></root>',path('root','r'),'<root><r><a/></r><footer/><r><a/></r></root>')

    def test_mixed_preserves_matching_alternate_presence_per_input_record(self):
        import copy
        v=variation();model=v['config']['returnModels'][0];model['outputXml']='<out><r><a>A</a><b>optional</b></r></out>'
        model['presence']={path('out','r','b'):{'requirement':'optional','include':True,'distribution':'alternate'}}
        second=copy.deepcopy(model);second.update(id='B',name='B');v['config']['returnModels'].append(second)
        result=generate_return(v,{'type':'all'},'mixed','<root><r><a>1</a></r><r><a>2</a></r></root>')[0]
        doc=minidom.parseString(result['content']);self.assertEqual([1,1,0,0],[len(r.getElementsByTagName('b')) for r in doc.getElementsByTagName('r')])

    def test_public_errors_do_not_expose_invalid_formula_values(self):
        v=variation();v['config']['rulesByMode']['new'][path('root','r','a')]={'generator':{'type':'sequence','start':'PRIVATE-FORMULA-VALUE'}}
        with self.assertRaises(ApiError) as caught:generate_new(v,1)
        self.assertNotIn('PRIVATE-FORMULA-VALUE',caught.exception.detail)
        model=v['config']['returnModels'][0];model['rules']={path('out','r','a'):{'generator':{'type':'sequence','start':'PRIVATE-RETURN-VALUE'}}}
        with self.assertRaises(ApiError) as caught:generate_return(v,{'type':'all'})
        self.assertNotIn('PRIVATE-RETURN-VALUE',caught.exception.detail)

    def test_input_and_output_limits_use_413(self):
        from unittest.mock import patch
        with self.assertRaises(ApiError) as caught:validate_return_input('<root><r><a/></r></root>',path('root','r'),'<root>'+('é'*1_000_000)+'</root>')
        self.assertEqual((413,'INPUT_TOO_LARGE'),(caught.exception.status,caught.exception.code))
        with patch('mockaize_api.xml_engine.OUTPUT_LIMIT',100):
            with self.assertRaises(ApiError) as caught:generate_new(variation(),10)
        self.assertEqual((413,'OUTPUT_LIMIT_EXCEEDED'),(caught.exception.status,caught.exception.code))

    def test_mixed_retains_namespace_bindings_from_each_source_envelope(self):
        import copy
        for prefix in ['b','']:
            v=variation();first=v['config']['returnModels'][0]
            group=json.dumps([{'ns':'urn:o','name':'out','index':1},{'ns':'urn:o','name':'r','index':1}])
            first.update(outputXml='<a:out xmlns:a="urn:o" xmlns:x="urn:attr"><a:r x:id="1"><a:v>A</a:v></a:r></a:out>',outputGroup=group,rules={})
            second=copy.deepcopy(first);second.update(id='B',name='B')
            second['outputXml']='<b:out xmlns:b="urn:o" xmlns:y="urn:attr"><b:r y:id="2"><b:v>B</b:v></b:r></b:out>' if prefix else '<out xmlns="urn:o" xmlns:y="urn:attr"><r y:id="2"><v>B</v></r></out>'
            v['config']['returnModels'].append(second)
            doc=minidom.parseString(generate_return(v,{'type':'all'},'mixed')[0]['content'])
            units=doc.getElementsByTagNameNS('urn:o','r');self.assertEqual(2,len(units));self.assertEqual('2',units[1].getAttributeNS('urn:attr','id'))
