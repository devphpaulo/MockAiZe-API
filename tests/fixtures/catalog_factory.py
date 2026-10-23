from contextlib import closing
"""SQLite format v2 fixture; contains no customer data."""
import json
import sqlite3


def create_catalog(path):
    group = json.dumps([{'ns': '', 'name': 'Document', 'index': 1},
                        {'ns': '', 'name': 'Record', 'index': 1}])
    xml = '<Document><Record><Value>example</Value></Record></Document>'
    models = [{'id': identity, 'name': name, 'selected': False,
               'outputXml': xml, 'outputGroup': group, 'rules': {},
               'presence': {}, 'filename': {'type': 'literal', 'value': name},
               'outputNotes': {}, 'headers': []}
              for identity, name in [('ret-a', 'Accepted'), ('ret-b', 'Rejected')]]
    config = {'mode': 'manual', 'inputByMode': {
        'new': {'xml': xml, 'group': group}, 'return': {'xml': xml, 'group': group}},
        'returnModels': models, 'activeReturnId': 'ret-b',
        'rulesByMode': {'new': {}, 'return': {}},
        'presenceByMode': {'new': {}, 'return': {}},
        'filenameByMode': {'new': {'type': 'literal', 'value': 'sample'}},
        'headersByMode': {'new': [], 'return': []}, 'baseDate': ''}
    with closing(sqlite3.connect(path)) as db, db:
        db.executescript('''
            CREATE TABLE app_meta(key TEXT PRIMARY KEY,value TEXT NOT NULL);
            CREATE TABLE schema_meta(key TEXT PRIMARY KEY,value TEXT NOT NULL);
            INSERT INTO app_meta VALUES('schema_version','2');
            INSERT INTO schema_meta VALUES('version','2');
            CREATE TABLE library_nodes(id TEXT PRIMARY KEY,parent_id TEXT,kind TEXT,
                name TEXT,deleted_at TEXT,created_at TEXT);
            CREATE TABLE variations(id TEXT PRIMARY KEY,specific_file_id TEXT,name TEXT,
                config_json TEXT,file_index INTEGER,revision INTEGER,created_at TEXT);
            INSERT INTO library_nodes VALUES('workspace',NULL,'workspace','Workspace',NULL,'2026-01-01');
            INSERT INTO library_nodes VALUES('folder','workspace','folder','Examples',NULL,'2026-01-01');
            INSERT INTO library_nodes VALUES('file-1','folder','variation','Sample',NULL,'2026-01-01');
        ''')
        db.execute('INSERT INTO variations VALUES(?,?,?,?,?,?,?)',
                   ('file-1', 'backing', 'Legacy name', json.dumps(config), 0, 7, '2026-01-01'))
