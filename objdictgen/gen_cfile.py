#!/usr/bin/env python
# -*- coding: utf-8 -*-

#This file is part of CanFestival, a library implementing CanOpen Stack. 
#
#Copyright (C): Edouard TISSERANT and Francis DUPIN
#
#See COPYING file for copyrights details.
#
#This library is free software; you can redistribute it and/or
#modify it under the terms of the GNU Lesser General Public
#License as published by the Free Software Foundation; either
#version 2.1 of the License, or (at your option) any later version.
#
#This library is distributed in the hope that it will be useful,
#but WITHOUT ANY WARRANTY; without even the implied warranty of
#MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the GNU
#Lesser General Public License for more details.
#
#You should have received a copy of the GNU Lesser General Public
#License along with this library; if not, write to the Free Software
#Foundation, Inc., 59 Temple Place, Suite 330, Boston, MA  02111-1307  USA

from node import *
from types import *

import re, os

word_model = re.compile('([a-zA-Z_0-9]*)')
type_model = re.compile('([\_A-Z]*)([0-9]*)')
range_model = re.compile('([\_A-Z]*)([0-9]*)\[([\-0-9]*)-([\-0-9]*)\]')

categories = [("SDO_SVR", 0x1200, 0x127F), ("SDO_CLT", 0x1280, 0x12FF),
              ("PDO_RCV", 0x1400, 0x15FF), ("PDO_RCV_MAP", 0x1600, 0x17FF),
              ("PDO_TRS", 0x1800, 0x19FF), ("PDO_TRS_MAP", 0x1A00, 0x1BFF)]
index_categories = ["firstIndex", "lastIndex"]

generated_tag = """\n/* File generated by gen_cfile.py. Should not be modified. */\n"""

# Format a string for making a C++ variable
def FormatName(name):
    wordlist = [word for word in word_model.findall(name) if word != '']
    result = ''
    sep = ''
    for word in wordlist:
        result += "%s%s"%(sep,word)
        sep = '_'
    return result

# Extract the informations from a given type name
def GetValidTypeInfos(typename):
    result = type_model.match(typename)
    if result:
        values = result.groups()
        if values[0] in ("UNSIGNED", "INTEGER") and eval(values[1]) in [i * 8 for i in xrange(1, 9)]:
            return "UNS%s"%values[1], "", "uint%s"%values[1]
        elif values[0] == "REAL" and eval(values[1]) in (32, 64):
            return "%s%s"%(values[0], values[1]), "", "real%s"%values[1]
        elif values[0] == "VISIBLE_STRING":
            if values[1] == "":
                return "UNS8", "[10]", "visible_string"
            else:
                return "UNS8", "[%s]"%values[1], "visible_string"
        elif values[0] == "DOMAIN":
        	return "UNS8*", "", "domain"
    return None

def WriteFile(filepath, content):
    cfile = open(filepath,"w")
    cfile.write(content)
    cfile.close()

def GenerateFileContent(Manager, headerfilepath):
    global type
    texts = {}
    texts["maxPDOtransmit"] = 0
    texts["NodeName"], texts["NodeID"], texts["NodeType"] = Manager.GetCurrentNodeInfos()
    internal_types = {}
    texts["iam_a_slave"] = 0
    if (texts["NodeType"] == "slave"):
        texts["iam_a_slave"] = 1
    
    # Compiling lists of indexes
    rangelist = [idx for name,idx in Manager.GetCurrentValidIndexes(0, 0x260)]
    listIndex = [idx for name,idx in Manager.GetCurrentValidIndexes(0x1000, 0xFFFF)]
    communicationlist = [idx for name,idx in Manager.GetCurrentValidIndexes(0x1000, 0x11FF)]
    sdolist = [idx for name,idx in Manager.GetCurrentValidIndexes(0x1200, 0x12FF)]
    pdolist = [idx for name,idx in Manager.GetCurrentValidIndexes(0x1400, 0x1BFF)]
    variablelist = [idx for name,idx in Manager.GetCurrentValidIndexes(0x2000, 0xBFFF)]

#-------------------------------------------------------------------------------
#                       Declaration of the value range types
#-------------------------------------------------------------------------------    
    
    valueRangeContent = ""
    strDefine = ""
    strSwitch = ""
    num = 0
    for index in rangelist:
        rangename = Manager.GetEntryName(index)
        result = range_model.match(rangename)
        if result:
            num += 1
            internal_types[rangename] = "valueRange_%d"%num
            typeindex = Manager.GetCurrentEntry(index, 1)
            typename = Manager.GetTypeName(typeindex)
            typeinfos = GetValidTypeInfos(typename)
            if typeinfos == None:
                raise ValueError, """!!! %s isn't a valid type for CanFestival."""%typename
            typename = typeinfos[0]
            minvalue = str(Manager.GetCurrentEntry(index, 2))
            maxvalue = str(Manager.GetCurrentEntry(index, 3))
            strDefine += "\n#define valueRange_%d 0x%02X /* Type %s, %s < value < %s */"%(num,index,typename,minvalue,maxvalue)
            strSwitch += """    case valueRange_%d:
      if (*(%s*)Value < (%s)%s) return OD_VALUE_TOO_LOW;
      if (*(%s*)Value > (%s)%s) return OD_VALUE_TOO_HIGH;
      break;\n"""%(num,typename,typename,minvalue,typename,typename,maxvalue)

    valueRangeContent += strDefine
    valueRangeContent += "\nUNS32 %(NodeName)s_valueRangeTest (UNS8 typeValue, void * value)\n{"%texts
    valueRangeContent += "\n  switch (typeValue) {\n"
    valueRangeContent += strSwitch
    valueRangeContent += "  }\n  return 0;\n}\n"

#-------------------------------------------------------------------------------
#            Creation of the mapped variables and object dictionary
#-------------------------------------------------------------------------------

    mappedVariableContent = ""
    strDeclareHeader = ""
    strDeclareCallback = ""
    indexContents = {}
    indexCallbacks = {}
    for index in listIndex:
        texts["index"] = index
        strIndex = ""
        entry_infos = Manager.GetEntryInfos(index)
        texts["EntryName"] = entry_infos["name"]
        values = Manager.GetCurrentEntry(index)
        callbacks = Manager.HasCurrentEntryCallbacks(index)
        if index in variablelist:
            strIndex += "\n/* index 0x%(index)04X :   Mapped variable %(EntryName)s */\n"%texts
        else:
            strIndex += "\n/* index 0x%(index)04X :   %(EntryName)s. */\n"%texts
        if type(values) == ListType:
            texts["value"] = values[0]
            strIndex += "                    UNS8 %(NodeName)s_highestSubIndex_obj%(index)04X = %(value)d; /* number of subindex - 1*/\n"%texts
        
        # Entry type is VAR
        if type(values) != ListType:
            subentry_infos = Manager.GetSubentryInfos(index, 0)
            typename = Manager.GetTypeName(subentry_infos["type"])
            typeinfos = GetValidTypeInfos(typename)
            if typeinfos == None:
                raise ValueError, """!!! %s isn't a valid type for CanFestival."""%typename
            if typename not in internal_types:
                internal_types[typename] = typeinfos[2]
            texts["subIndexType"] = typeinfos[0]
            texts["suffixe"] = typeinfos[1]
            if typeinfos[2] == "visible_string":
                texts["value"] = "\"%s\""%values
                texts["comment"] = ""
            else:
                texts["value"] = "0x%X"%values
                texts["comment"] = "\t/* %s */"%str(values)
            if index in variablelist:
                texts["name"] = FormatName(subentry_infos["name"])
                strDeclareHeader += "extern %(subIndexType)s %(name)s%(suffixe)s;\t\t/* Mapped at index 0x%(index)04X, subindex 0x00*/\n"%texts
                if callbacks:
                    strDeclareHeader += "extern ODCallback_t %(name)s_callbacks[];\t\t/* Callbacks of index0x%(index)04X */\n"%texts
                mappedVariableContent += "%(subIndexType)s %(name)s%(suffixe)s = %(value)s;\t\t/* Mapped at index 0x%(index)04X, subindex 0x00 */\n"%texts
            else:
                strIndex += "                    %(subIndexType)s %(NodeName)s_obj%(index)04X%(suffixe)s = %(value)s;%(comment)s\n"%texts
            values = [values]
        else:
            
            # Entry type is RECORD
            if entry_infos["struct"] & OD_IdenticalSubindexes:
                subentry_infos = Manager.GetSubentryInfos(index, 1)
                typename = Manager.GetTypeName(subentry_infos["type"])
                typeinfos = GetValidTypeInfos(typename)
                if typeinfos == None:
                    raise ValueError, """!!! %s isn't a valid type for CanFestival."""%typename
                if typename not in internal_types:
                    internal_types[typename] = typeinfos[2]
                texts["subIndexType"] = typeinfos[0]
                texts["suffixe"] = typeinfos[1]
                texts["length"] = values[0]
                if index in variablelist:
                    texts["name"] = FormatName(entry_infos["name"])
                    strDeclareHeader += "extern %(subIndexType)s %(name)s[%(length)d]%(suffixe)s;\t\t/* Mapped at index 0x%(index)04X, subindex 0x01 - 0x%(length)02X */\n"%texts
                    if callbacks:
                        strDeclareHeader += "extern ODCallback_t %(name)s_callbacks[];\t\t/* Callbacks of index0x%(index)04X */\n"%texts
                    mappedVariableContent += "%(subIndexType)s %(name)s[] =\t\t/* Mapped at index 0x%(index)04X, subindex 0x01 - 0x%(length)02X */\n  {\n"%texts
                    for subIndex, value in enumerate(values):
                        sep = ","
                        comment = ""
                        if subIndex > 0:
                            if subIndex == len(values)-1:
                                sep = ""
                            if typeinfos[2] == "visible_string":
                                value = "\"%s\""%value
                            else:
                                comment = "\t/* %s */"%str(value)
                                value = "0x%X"%value
                            mappedVariableContent += "    %s%s%s\n"%(value, sep, comment)
                    mappedVariableContent += "  };\n"
                else:
                    strIndex += "                    %(subIndexType)s %(NodeName)s_obj%(index)04X[] = \n                    {\n"%texts
                    for subIndex, value in enumerate(values):
                        sep = ","
                        comment = ""
                        if subIndex > 0:
                            if subIndex == len(values)-1:
                                sep = ""
                            if typeinfos[2] == "visible_string":
                                value = "\"%s\""%value
                            if typeinfos[2] == "domain":
                                value = "\"%s\""%''.join(["\\x%2.2x"%ord(char) for char in value])
                            else:
                                comment = "\t/* %s */"%str(value)
                                value = "0x%X"%value
                            strIndex += "                      %s%s%s\n"%(value, sep, comment)
                    strIndex += "                    };\n"
            else:
                
                texts["parent"] = FormatName(entry_infos["name"])
                # Entry type is ARRAY
                for subIndex, value in enumerate(values):
                    texts["subIndex"] = subIndex
                    if subIndex > 0:
                        subentry_infos = Manager.GetSubentryInfos(index, subIndex)
                        typename = Manager.GetTypeName(subentry_infos["type"])
                        typeinfos = GetValidTypeInfos(typename)
                        if typeinfos == None:
                            raise ValueError, """!!! %s isn't a valid type for CanFestival."""%typename
                        if typename not in internal_types:
                            internal_types[typename] = typeinfos[2]
                        texts["subIndexType"] = typeinfos[0]
                        texts["suffixe"] = typeinfos[1]
                        if typeinfos[2] == "visible_string":
                            texts["value"] = "\"%s\""%value
                            texts["comment"] = ""
                        else:
                            texts["value"] = "0x%X"%value
                            texts["comment"] = "\t/* %s */"%str(value)
                        texts["name"] = FormatName(subentry_infos["name"])
                        if index in variablelist:
                            strDeclareHeader += "extern %(subIndexType)s %(parent)s_%(name)s%(suffixe)s;\t\t/* Mapped at index 0x%(index)04X, subindex 0x%(subIndex)02X */\n"%texts
                            mappedVariableContent += "%(subIndexType)s %(parent)s_%(name)s%(suffixe)s = %(value)s;\t\t/* Mapped at index 0x%(index)04X, subindex 0x%(subIndex)02X */\n"%texts
                        else:
                            strIndex += "                    %(subIndexType)s %(NodeName)s_obj%(index)04X_%(name)s%(suffixe)s = %(value)s;%(comment)s\n"%texts
                if callbacks:
                    strDeclareHeader += "extern ODCallback_t %(parent)s_callbacks[];\t\t/* Callbacks of index0x%(index)04X */\n"%texts
        
        # Generating Dictionary C++ entry
        if callbacks:
            if index in variablelist:
                name = FormatName(entry_infos["name"])
            else:
                name = "%(NodeName)s_Index%(index)04X"%texts
            strIndex += "                    ODCallback_t %s_callbacks[] = \n                     {\n"%name
            for subIndex in xrange(len(values)):
                strIndex += "                       NULL,\n"
            strIndex += "                     };\n"
            indexCallbacks[index] = "*callbacks = %s_callbacks; "%name
        else:
            indexCallbacks[index] = ""
        strIndex += "                    subindex %(NodeName)s_Index%(index)04X[] = \n                     {\n"%texts
        for subIndex in xrange(len(values)):
            subentry_infos = Manager.GetSubentryInfos(index, subIndex)
            if subIndex < len(values) - 1:
                sep = ","
            else:
                sep = ""
            typename = Manager.GetTypeName(subentry_infos["type"])
            typeinfos = GetValidTypeInfos(typename)
            if typename.startswith("VISIBLE_STRING"):
                subIndexType = "visible_string"
            elif typename in internal_types:
                subIndexType = internal_types[typename]
            else:
                subIndexType = typename
            if subIndex == 0:
                if entry_infos["struct"] & OD_MultipleSubindexes:
                    name = "%(NodeName)s_highestSubIndex_obj%(index)04X"%texts
                elif index in variablelist:
                    name = FormatName(subentry_infos["name"])
                else:
                    name = FormatName("%s_obj%04X"%(texts["NodeName"], texts["index"]))
            elif entry_infos["struct"] & OD_IdenticalSubindexes:
                if index in variablelist:
                    name = "%s[%d]"%(FormatName(entry_infos["name"]), subIndex - 1)
                else:
                    name = "%s_obj%04X[%d]"%(texts["NodeName"], texts["index"], subIndex - 1)
            else:
                if index in variablelist:
                    name = FormatName("%s_%s"%(entry_infos["name"],subentry_infos["name"]))
                else:
                    name = "%s_obj%04X_%s"%(texts["NodeName"], texts["index"], FormatName(subentry_infos["name"]))
            if subIndexType in ["visible_string", "domain"]:
                sizeof = str(len(values[subIndex]))
            else:
                sizeof = "sizeof (%s)"%typeinfos[0]
            params = Manager.GetCurrentParamsEntry(index, subIndex)
            if params["save"]:
                save = "|TO_BE_SAVE"
            else:
                save = ""
            strIndex += "                       { %s%s, %s, %s, (void*)&%s }%s\n"%(subentry_infos["access"].upper(),save,subIndexType,sizeof,name,sep)
        strIndex += "                     };\n"
        indexContents[index] = strIndex

#-------------------------------------------------------------------------------
#                     Declaration of Particular Parameters
#-------------------------------------------------------------------------------

    if 0x1006 not in communicationlist:
        entry_infos = Manager.GetEntryInfos(0x1006)
        texts["EntryName"] = entry_infos["name"]
        indexContents[0x1006] = """\n/* index 0x1006 :   %(EntryName)s */
                    UNS32 %(NodeName)s_obj1006 = 0x0;   /* 0 */
"""%texts

    if 0x1016 in communicationlist:
        texts["nombre"] = Manager.GetCurrentEntry(0x1016, 0)
    else:
        texts["nombre"] = 0
        entry_infos = Manager.GetEntryInfos(0x1016)
        texts["EntryName"] = entry_infos["name"]
        indexContents[0x1016] = """\n/* index 0x1016 :   %(EntryName)s */
                    UNS8 %(NodeName)s_highestSubIndex_obj1016 = 0;
                    UNS32 %(NodeName)s_obj1016[]={0};
"""%texts
    if texts["nombre"] > 0:
        strTimers = "TIMER_HANDLE %(NodeName)s_heartBeatTimers[%(nombre)d] = {TIMER_NONE,};\n"%texts
    else:
        strTimers = "TIMER_HANDLE %(NodeName)s_heartBeatTimers[1];\n"%texts

    if 0x1017 not in communicationlist:
        entry_infos = Manager.GetEntryInfos(0x1017)
        texts["EntryName"] = entry_infos["name"]
        indexContents[0x1017] = """\n/* index 0x1017 :   %(EntryName)s */ 
                    UNS16 %(NodeName)s_obj1017 = 0x0;   /* 0 */
"""%texts

#-------------------------------------------------------------------------------
#               Declaration of navigation in the Object Dictionary
#-------------------------------------------------------------------------------

    strDeclareIndex = ""
    strDeclareSwitch = ""
    strQuickIndex = ""
    quick_index = {}
    for index_cat in index_categories:
        quick_index[index_cat] = {}
        for cat, idx_min, idx_max in categories:
            quick_index[index_cat][cat] = 0
    maxPDOtransmit = 0
    for i, index in enumerate(listIndex):
        texts["index"] = index
        strDeclareIndex += "  { (subindex*)%(NodeName)s_Index%(index)04X,sizeof(%(NodeName)s_Index%(index)04X)/sizeof(%(NodeName)s_Index%(index)04X[0]), 0x%(index)04X},\n"%texts
        strDeclareSwitch += "		case 0x%04X: i = %d;%sbreak;\n"%(index, i, indexCallbacks[index])
        for cat, idx_min, idx_max in categories:
            if idx_min <= index <= idx_max:
                quick_index["lastIndex"][cat] = i
                if quick_index["firstIndex"][cat] == 0:
                    quick_index["firstIndex"][cat] = i
                if cat == "PDO_TRS":
                    maxPDOtransmit += 1
    texts["maxPDOtransmit"] = max(1, maxPDOtransmit)
    for index_cat in index_categories:
        strQuickIndex += "\nquick_index %s_%s = {\n"%(texts["NodeName"], index_cat)
        sep = ","
        for i, (cat, idx_min, idx_max) in enumerate(categories):
            if i == len(categories) - 1:
                sep = ""
            strQuickIndex += "  %d%s /* %s */\n"%(quick_index[index_cat][cat],sep,cat)
        strQuickIndex += "};\n"

#-------------------------------------------------------------------------------
#                            Write File Content
#-------------------------------------------------------------------------------

    fileContent = generated_tag + """
#include "%s"
"""%(headerfilepath)

    fileContent += """
/**************************************************************************/
/* Declaration of the mapped variables                                    */
/**************************************************************************/
""" + mappedVariableContent

    fileContent += """
/**************************************************************************/
/* Declaration of the value range types                                   */
/**************************************************************************/
""" + valueRangeContent

    fileContent += """
/**************************************************************************/
/* The node id                                                            */
/**************************************************************************/
/* node_id default value.*/
UNS8 %(NodeName)s_bDeviceNodeId = 0x%(NodeID)02X;

/**************************************************************************/
/* Array of message processing information */

const UNS8 %(NodeName)s_iam_a_slave = %(iam_a_slave)d;

"""%texts
    fileContent += strTimers
    
    fileContent += """
/*
$$$$$$$$$$$$$$$$$$$$$$$$$$$$$$$$$$$$$$$$$$$$$$$$$$$$$$$$$$$$$$$$$$$$$$$$$$$

                               OBJECT DICTIONARY

$$$$$$$$$$$$$$$$$$$$$$$$$$$$$$$$$$$$$$$$$$$$$$$$$$$$$$$$$$$$$$$$$$$$$$$$$$$
*/
"""%texts
    contentlist = indexContents.keys()
    contentlist.sort()
    for index in contentlist:
        fileContent += indexContents[index]

    fileContent += """
const indextable %(NodeName)s_objdict[] = 
{
"""%texts
    fileContent += strDeclareIndex
    fileContent += """};

const indextable * %(NodeName)s_scanIndexOD (UNS16 wIndex, UNS32 * errorCode, ODCallback_t **callbacks)
{
	int i;
	*callbacks = NULL;
	switch(wIndex){
"""%texts
    fileContent += strDeclareSwitch
    fileContent += """		default:
			*errorCode = OD_NO_SUCH_OBJECT;
			return NULL;
	}
	*errorCode = OD_SUCCESSFUL;
	return &%(NodeName)s_objdict[i];
}

/* To count at which received SYNC a PDO must be sent.
 * Even if no pdoTransmit are defined, at least one entry is computed
 * for compilations issues.
 */
UNS8 %(NodeName)s_count_sync[%(maxPDOtransmit)d] = {0,};
"""%texts
    fileContent += strQuickIndex
    fileContent += """
UNS16 %(NodeName)s_ObjdictSize = sizeof(%(NodeName)s_objdict)/sizeof(%(NodeName)s_objdict[0]); 

CO_Data %(NodeName)s_Data = CANOPEN_NODE_DATA_INITIALIZER(%(NodeName)s);

"""%texts

#-------------------------------------------------------------------------------
#                          Write Header File Content
#-------------------------------------------------------------------------------

    HeaderFileContent = generated_tag + """
#include "data.h"

/* Prototypes of function provided by object dictionnary */
UNS32 %(NodeName)s_valueRangeTest (UNS8 typeValue, void * value);
const indextable * %(NodeName)s_scanIndexOD (UNS16 wIndex, UNS32 * errorCode, ODCallback_t **callbacks);

/* Master node data struct */
extern CO_Data %(NodeName)s_Data;

"""%texts
    HeaderFileContent += strDeclareHeader
    
    return fileContent,HeaderFileContent

#-------------------------------------------------------------------------------
#                             Main Function
#-------------------------------------------------------------------------------

def GenerateFile(filepath, manager):
    headerfilepath = os.path.splitext(filepath)[0]+".h"
    content, header = GenerateFileContent(manager, os.path.split(headerfilepath)[1])
    WriteFile(filepath, content)
    WriteFile(headerfilepath, header)
    return True
