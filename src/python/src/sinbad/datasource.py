'''
Created on Aug 24, 2017

@author: nhamid
'''

from jsonpath_rw import parse
import urllib.parse
from zipfile import ZipFile, BadZipfile
import random

import cacher as C
import util as U

import plugin_csv
import plugin_json
import plugin_xml



class DataSource:
    '''
    classdocs
    '''
    
    __predefined_plugins = [ { "name" : "JSON (built-in)", 
                               "type-ext" : "json",
                               "data-infer" : plugin_json.JSON_Infer(),
                               "data-factory" : plugin_json.JSON_Data_Factory },
                            { "name" : "XML (lxml)", 
                               "type-ext" : "xml",
                               "data-infer" : plugin_xml.XML_Infer(),
                               "data-factory" : plugin_xml.XML_Data_Factory },
                            { "name" : "CSV (built-in)",
                               "type-ext" : "csv",
                               "data-infer" : plugin_csv.CSV_Infer(),
                               "data-factory" : plugin_csv.CSV_Data_Factory }
                        ]
    
    plugins = __predefined_plugins
    
    @staticmethod
    def connect(path):
        for p in DataSource.plugins:
            if p["data-infer"].matched_by(path):
                return DataSource(path, path, p["type-ext"], p)
        
        raise ValueError('could not infer data format for {}'.format(path))
    
    @staticmethod
    def connect_as(type_ext, path):
        type_ext = type_ext.lower()
        for p in DataSource.plugins:
            if p["type-ext"] == type_ext:
                return DataSource(path, path, type_ext, p)

        raise ValueError("no data source plugin for type {}".format(type_ext))
        

    def __init__(self, name, path, typeExt, plugin):
        '''
        (usual use is to call DataSource.connect() to instantiate objects of
         this class) 
        '''
        
        self.name = name
        self.path = path
        self.format_type = typeExt
        
        self.__connected = path and True
        self.__load_ready = False
        self.__loaded = False
        
        self.data_infer = plugin["data-infer"]
        self.data_factory = plugin["data-factory"]()
        self.data_obj = None
        self.cacher = C.defaultCacher()
        
        self.param_values = {}



    def set_param(self, name, value):
        self.param_values[name] = value
        return self
        

    def load(self, force_reload = False):
        if not self.__connected: raise ValueError("not __connected {}".format(self.path))
        if not self.__ready_to_load(): raise ValueError("not ready to load; missing params...")
        
        subtag = "main"
        schemaSubtag = "schema"
    
        full_path = self.get_full_path_url()
    
        if self.__loaded and \
                not self.cacher.is_stale(full_path, subtag) and \
                not force_reload:
            return self
        
        resolved_path = self.cacher.resolvePath(full_path, subtag, {})
        
        # TODO
        options = {}
        fp = U.create_input(resolved_path, options)
        
        print("Full path: {} {}".format(full_path, U.smellsLikeZip(full_path)))
        if U.smellsLikeZip(full_path) and not U.smellsLikeURL(resolved_path):
            try:
                zf = ZipFile(resolved_path)
                print("***** ZIP *****")
                members = zf.namelist()
                print(members)
                
                if len(members) == 1:
                    fp = zf.open(members[0])
            except BadZipfile:
                print("ZIP Failed: " + full_path)
        
        
        self.data_obj = self.data_factory.load_data(fp)
        
        self.loaded = True
        return self


    def fetch(self):
        return self.data_obj


    def patch_jsonpath_path(self, pth, data):
        pth = pth.replace("/", ".")
        splits = pth.split(".")
        if not splits:
            return pth
        
        fixed_path = ""
        for piece in splits:
            if fixed_path: fixed_path = fixed_path + "."
            fixed_path = fixed_path + piece
            #print("checking " + fixed_path)
            selected = parse(fixed_path).find(data)
            if len(selected) == 1 and type(selected[0].value) == list and \
                    len(selected[0].value) > 1 and not fixed_path.endswith("]"):
                #print("adding *: {} b/c {}".format(fixed_path, str(selected[0].value)))
                fixed_path = fixed_path + "[*]"
                
        return fixed_path         

    def fetch_random(self, *field_paths, base_path = None):
        return self.fetch_extract(*field_paths, base_path = base_path, select = "random")
    
    def fetch_extract(self, *field_paths, base_path = None, select = None):
        data = self.fetch()
        
        collected = []

        if base_path:      
            base_path = self.patch_jsonpath_path(base_path, data)
            data = parse(base_path).find(data)
        elif not isinstance(data, list):
                data = [data]
        
        parsed_paths = None
        field_names = None

        for match in data:
            if parsed_paths is None:
                parsed_paths = []
                field_names = []
                for field_path in field_paths:
                    field_path = self.patch_jsonpath_path(field_path, match)
                    field_name = field_path.split(".")[-1]    # TODO: could end up with [...] at end of field names
                    parsed_paths.append(parse(field_path))
                    field_names.append(field_name)
            
            d = {}
            for fp, fn in zip(parsed_paths, field_names):
                fv = fp.find(match)
                if len(fv) == 1:
                    d[fn] = fv[0].value
                else:
                    d[fn] = [v.value for v in fv]
            collected.append(d)
        
        if len(collected) == 1:
            return collected[0]
        else:
            if select and select.lower() == 'random' and isinstance(collected, list):
                return random.choice(collected)
            else:
                return collected
        
        #=======================================================================
        # if len(base_match) == 1:
        #     if not field_paths:
        #         return base_match[0].value
        #     else:
        #         d = {}
        #         base_path = base_path.replace("/", ".")
        #         base_name = base_path.split(".")[-1]
        #         d[base_name] = base_match[0].value
        #         for field_path in field_paths:
        #             field_path = field_path.replace("/", ".")
        #             field_name = field_path.split(".")[-1]
        #             fv = parse(field_path).find(base_match[0])
        #             if len(fv) == 1:
        #                 d[field_name] = fv[0].value
        #             else:
        #                 d[field_name] = [v.value for v in fv]
        #         return d
        # else:
        #=======================================================================
    

    def set_cache_timeout(self, value):
        ''' set the cache delay to the given value in seconds '''
        self.cacher = self.cacher.updateTimeout(value * 1000)
        return self


    def set_option(self, name, value):
        # TODO: zip file entry
        self.data_factory.set_option(name, value)


    def get_full_path_url(self):
        if not self.__ready_to_load():
            raise ValueError("Cannot finalize path: not ready to load")
        
        full_path = self.path
        
        # TODO ...
        params = urllib.parse.urlencode(self.param_values)
        if params:
            full_path = full_path + "?" + params
        
        return full_path


    def __ready_to_load(self):
        # TODO...
        self.__load_ready = self.__load_ready # or  missingParams().size()==0;
        
        self.__load_ready = True
        return self.__load_ready;



'''

   A <data-plugin> is a dictionary:
    {  "name" : string,
       "type-ext" : string,
       "data-infer" : <data infer object>,
       "data-factory" : <data access factory object> }
       
       
    A <data infer object> has one method:
        boolean matched_by(String path)
            path: the primary path (URL/file name) to the data
    and one field: 
        options: dict  { String : String, ... }
        
        
    A <data access factory object> has methods:
        
    
        set_option(name, value)
    
        <data object>  load_data(fp)
            fp : a file object (binary mode)
            returns a dict-like thing with a 
            
    <data object> = a dict-like thing with 
        get schema
        ability to produce an actual dict (possibly pruned from the entire available data)
        

'''