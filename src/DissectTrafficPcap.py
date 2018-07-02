import json
import sys
import os

# global variables for common header types
ETHER_DETECT = False
IPv4_DETECT = False
IPv6_DETECT = False
TCP_DETECT = False
UDP_DETECT = False

DEBUG = False

# open file to load json data
# standardize destination path
try:
    data = json.load(open(sys.argv[1]))
    DESTINATION = sys.argv[2]
    if (DESTINATION[-1] != '/'):
        DESTINATION += '/'
    print ("Generating Pcap++ dissector for %s at %s\n" %(sys.argv[1], DESTINATION))

except IndexError:
    print ("Incorrect argument specification")
    exit(0)
except IOError:
    print ("Incorrect file specification")
    exit(0)

# check if debug mode activated or not
if (len(sys.argv) > 3):
    if (sys.argv[-1] == '-d'):
        DEBUG = True

# variable to store the list of tables created by the scripts
tables_created = []

# assign valid name to state depending on which header it extracts
def valid_state_name(state):
    if len(state["parser_ops"]) > 0:
        if type(state["parser_ops"][0]["parameters"][0]["value"]) is list:
            return state["parser_ops"][0]["parameters"][0]["value"][0]
        else:
            return state["parser_ops"][0]["parameters"][0]["value"]
    else:
        return state["name"]

# search for valid state name in the parse states
def search_state(parser, name):
    for state in parser["parse_states"]:
        if (state["name"] == name):
            return valid_state_name(state)

# search for header type given the header_type_name specified in header definition
def search_header_type(header_types, name):
    for header_type in header_types:
        if (header_type["name"] == name):
            return header_type

# find headers and their types which appear within a packet i.e. are not metadata
def find_data_headers(headers, header_types):
    global ETHER_DETECT
    global IPv4_DETECT
    global IPv6_DETECT
    global TCP_DETECT
    global UDP_DETECT

    header_ports = []
    header_dict = {}

    for header_id in range(len(headers)):
        global input
        try:
            input = raw_input
        except NameError:
            pass
        if (headers[header_id]['metadata']) == False:
            name = headers[header_id]['name']
            if (name.find('[') != (-1)):
                name = name[:name.find('[')]
            header_ports.append(name)
            header_dict[name] = search_header_type(
                header_types, headers[header_id]["header_type"])

            # functionality to use common headers to be added
            if (name=='ethernet'):
                print("\nEthernet header detected, would you like the standard ethernet header to be used(y/n) :")
                temp = input().strip()
                if (temp == 'y'):
                    ETHER_DETECT = True
                    print("\nAdd the next layers in the function resolveNextHeader of Ethernet\n")
            elif (name=='ipv4'):
                print("\nIPv4 header detected, would you like the standard IPv4 header to be used(y/n) : ")
                temp = input().strip()
                if (temp == 'y'):
                    IPv4_DETECT = True
                    print("\nAdd the next layers in the function resolveNextHeader of IPv4\n")

            elif (name=='ipv6'):
                print("\nIPv6 header detected, would you like the standard IPv6 header to be used(y/n) : ")
                temp = input().strip()
                if (temp == 'y'):
                    IPv6_DETECT = True
                    print("\nAdd the next layers in the function resolveNextHeader of IPv6\n")

            elif (name=='tcp'):
                print("\nTCP header detected, would you like the standard TCP header to be used(y/n) : ")
                temp = input().strip()
                if (temp == 'y'):
                    TCP_DETECT = True
                    print("\nAdd the next layers in the function resolveNextHeader of TCP\n")

            elif (name=='udp'):
                print("\nUDP header detected, would you like the standard UDP header to be used(y/n) :")
                temp = input().strip()
                if (temp == 'y'):
                    UDP_DETECT = True
                    print("\nAdd the next layers in the function resolveNextHeader of UDP\n")

    header_ports = list(set(header_ports))

    header_types = []
    for i in header_ports:
        header_types.append(header_dict[i])

    if (DEBUG):
        print("\nHeaders \n")
        for i in range(len(header_ports)):
            print (header_ports[i], header_types[i]["name"])
    return (header_ports, header_types)

# make a control graph for all possible state transitions
# returns the list of edges in graph
def make_control_graph(parsers):
    graph = []
    for parser in parsers:
        for state in parser["parse_states"]:
            name = valid_state_name(state)
            if len(state["transition_key"]) > 0:
                for transition in state["transitions"]:
                    if transition["next_state"] != None:
                        graph.append([name,
                                      state["transition_key"][0]["value"][1],
                                      transition["value"],
                                      search_state(
                                          parser, transition["next_state"])
                                      ])
                    else:
                        graph.append([name, None, None, "final"])
            else:
                if state["transitions"][0]["next_state"] != None:
                    graph.append([name, None, None, search_state(
                        parser, state["transitions"][0]["next_state"])])
                else:
                    graph.append([name, None, None, "final"])
    if (DEBUG):
        print("\nEdges in the control_graph\n")
        for i in graph:
            print(i)
    return graph

# copies template file contents 
def copy_template(fout):
    fin  = open("../templates/templateMoonGen.lua","r")
    l = fin.readlines()
    for i in l:
        fout.write(i)

def predict_type(field):
    if (field<=8):
        return "uint8_t"
    if (field<=16):
        return "uint16_t"
    # if (field<=24):
    #     return "union bitfield_24"
    if (field<=32):
        return "uint32_t"
    # if (field<=40):
    #     return "union bitfield_40"
    # if (field<=48):
    #     return "union bitfield_48"
    if (field<=64):
        return "uint64_t"
    return "-- fill blank here " + str(field)

def network_host_conversion(field):
    if (field[1]<=8):
        return ""
    if (field[1]<=16):
        return "ntoh16"
    if (field[1]<=32):
        return "ntoh"
    if (field[1]<=64):
        return "ntoh64"
    return "-- fill blank here"

def host_network_conversion(field):
    if (field[1]<=8):
        return ""
    if (field[1]<=16):
        return "htons"
    # if (field[1]<=24):
    #     return ""
    if (field[1]<=32):
        return "htonl"
    # if (field[1]<=40):
    #     return ""
    # if (field[1]<=48):
    #     return ""
    if (field[1]<=64):
        return "htobe64"
    return "-- fill blank here"

# makes the actual lua script given the relevant header type and next and previous state transition information
def make_template(control_graph, header, header_type, destination, header_ports):
    if ((ETHER_DETECT or IPv4_DETECT or IPv6_DETECT or TCP_DETECT or UDP_DETECT) == False):
        headerUpper = header.upper()
        fout_header = open(destination + ".h","w")
        fout_source = open(destination + ".cpp","w")

        fout_header.write("//Template for addition of new protocol '%s'\n\n" %(header))
        fout_header.write("#ifndef %s\n" %("P4_"+header.upper()+"_LAYER"))
        fout_header.write("#define %s\n\n" %("P4_"+header.upper()+"_LAYER"))
        fout_header.write("#include \"Layer.h\"\n")
        fout_header.write("#ifdef defined(WIN32) || defined(WINx64)\n#include <winsock2.h>\n#elif LINUX\n#include <in.h>\n#endif\n\n")
        fout_header.write("namespace pcpp{\n\t#pragma pack(push,1)\n")
        fout_header.write("\tstruct %s{\n" %(header.lower()+"hdr"))
        
        variable_fields = []
        for field in header_type["fields"]:
            try:
                fout_header.write("\t\t%s \t %s;\n" %(predict_type(field[1]),field[0]))
            except TypeError:
                variable_fields.append(field[0])
        if (len(variable_fields)>0):
            fout_header.write("\n\t\t// variable length fields\n")
        for variable_field in variable_fields:
            fout_header.write("%s\n" %(variable_field))
        fout_header.write("\t};\n\n")

        fout_header.write("\t#pragma pack(pop)\n")
        fout_header.write("\tclass %sLayer: public Layer{\n" %(header.capitalize()))
        fout_header.write("\t\tpublic:\n")
        fout_header.write("\t\t %sLayer(uint8_t* data, size_t dataLen, Layer* prevLayer, Packet* packet): Layer(data, dataLen, prevLayer, packet) {m_Protocol = P4_%s;}\n" %(header.capitalize(), header.upper()))
       
        fout_header.write("\n\t\t // Getters for fields\n")

        for field in header_type["fields"]:
            try:
                fout_header.write("\t\t %s get%s();\n" %(predict_type(field[1]),str(field[0]).capitalize()))
            except TypeError:
                field[1] = int(input('Variable length field ' + field[0] + ' detected in ' + header + '. Enter its length\n'))
                fout_header.write("\t\t %s get%s();\n" %(predict_type(field[1]),str(field[0]).capitalize()))

        fout_header.write("\n\t\t inline %shdr* get%sHeader() { return (%shdr*)m_Data; }\n\n" %(header.lower(), header.capitalize(), header.lower()))
        fout_header.write("\t\t void parseNextLayer();\n\n")
        fout_header.write("\t\t inline size_t getHeaderLen() { return sizeof(%shdr); }\n\n" %(header.lower()))
        fout_header.write("\t\t void computeCalculateField() {}\n\n")
        fout_header.write("\t\t std::string toString();\n\n")
        fout_header.write("\t\t OsiModelLayer getOsiModelLayer() { return OsiModelApplicationLayer; }\n\n")
        fout_header.write("\t};\n")
        fout_header.write("}\n#endif")
        fout_header.close()

        fout_source.write("#define LOG_MODULE PacketLogModule%sLayer\n\n" %(header.capitalize()))
        fout_source.write("#include \"%sLayer.h\"\n" %(header.capitalize()))
        fout_source.write("#include \"PayloadLayer.h\"\n#include \"IpUtils.h\"\n#include \"Logger.h\"\n")
        fout_source.write("#include <string.h>\n#include <sstream>\n#include <endian.h>\n\n")
        fout_source.write("namespace pcpp{\n")

        for field in header_type["fields"]:
            try:
                fout_source.write("\t%s %sLayer::get%s(){\n" %(predict_type(field[1]), header.capitalize(), str(field[0]).capitalize()))
                fout_source.write("\t\t%s %s;\n" %(predict_type(field[1]), field[0]))
                fout_source.write("\t\t%shdr* hdrdata = (%shdr*)m_Data;\n" %(header.lower(),header.lower()))
                fout_source.write("\t\t%s = %s(hdrdata->%s);\n" %(field[0],host_network_conversion(field), field[0]))
                fout_source.write("\t\treturn %s;\n\t}\n\n" %(field[0]))
            except TypeError:
                field[1] = int(input('Variable length field ' + field[0] + ' detected in ' + header + '. Enter its length\n'))
                fout_source.write("\t%s %sLayer::get%s(){\n" %(predict_type(field[1]), header.capitalize(), str(field[0]).capitalize()))
                fout_source.write("\t\t%s %s;\n" %(predict_type(field[1]), field[0]))
                fout_source.write("\t\t%shdr* hdrdata = (%shdr*)m_Data;\n" %(header.lower(),header.lower()))
                fout_source.write("\t\t%s = %s(hdrdata->%s);\n" %(field[0],host_network_conversion(field), field[0]))
                fout_source.write("\t\treturn %s;\n\t}\n\n" %(field[0]))

        default_next_transition = None
        transition_key = None
        next_transitions = []
        for edge in control_graph:
            if (header==edge[0]):
                if (edge[1]!=None):
                    transition_key = edge[1]
                    next_transitions.append((edge[-1],edge[-2]))
                else:
                    default_next_transition = edge[-1]

        fout_source.write("\tvoid %sLayer::parseNextLayer(){\n" %(header.capitalize()))
        fout_source.write("\t\tif (m_DataLen <= sizeof(%shdr))\n" %(header.lower()))
        fout_source.write("\t\t\treturn;\n\n")

        if (len(next_transitions)>0):
            fout_source.write("\t\t%shdr* hdrdata = get%sHeader();\n" %(header.lower(), header.capitalize()))
            for field in header_type["fields"]:
                if (field[0]==transition_key):
                    size = field[1]
                    break
            fout_source.write("\t\t%s %s = %s(hdrdata->%s);\n\t\t" %(predict_type(field[1]), transition_key,host_network_conversion(field), transition_key))
            for transition in next_transitions[:-1]:
                #print transition
                fout_source.write("if (%s == %s)\n" %(transition_key, transition[1]))
                fout_source.write("\t\t\tm_NextLayer = new %sLayer(m_Data+sizeof(%shdr), m_DataLen - sizeof(%shdr), this, m_Packet);\n" %(transition[0].capitalize(),header.lower(), header.lower()))
                fout_source.write("\t\telse ")
            transition = next_transitions[-1]
            fout_source.write("if (%s == %s)\n" %(transition_key, transition[1]))
            fout_source.write("\t\t\tm_NextLayer = new %sLayer(m_Data+sizeof(%shdr), m_DataLen - sizeof(%shdr), this, m_Packet);\n" %(transition[0].capitalize(),header.lower(), header.lower()))

            if (default_next_transition!=None):
                fout_source.write("\t\telse\n")
                if (default_next_transition=="final"):
                    fout_source.write("\t\t\tm_NextLayer = new PayloadLayer(m_Data + sizeof(%shdr), m_DataLen - sizeof(%shdr), this, m_Packet);\n\t}\n" %(header.lower(),header.lower()))
                else:
                    fout_source.write("\t\t\tm_NextLayer = new default_next_transition(m_Data + sizeof(%shdr), m_DataLen - sizeof(%shdr), this, m_Packet);\n\t}\n" %(header.lower(),header.lower()))

        fout_source.write("\n\tstd::string %sLayer::toString(){}\n\n" %(header.capitalize()))


control_graph = make_control_graph(data["parsers"])
header_ports, header_types = find_data_headers(
    data["headers"], data["header_types"])
local_name = sys.argv[1][sys.argv[1].rfind('/')+1:sys.argv[1].rfind('.')]


for i in range(len(header_ports)):
    if ((ETHER_DETECT and header_ports[i]=='ethernet') or (IPv4_DETECT and header_ports[i]=='ipv4') or (IPv6_DETECT and header_ports[i]=='ipv6') or (TCP_DETECT and header_ports[i]=='tcp') or (UDP_DETECT and header_ports[i]=='udp')):
        continue
    destination = DESTINATION + local_name + "_" + \
        header_ports[i]
    make_template(control_graph, header_ports[i], header_types[i], destination, header_ports)

if (DEBUG):
    print ("\nTables created\n")
    for i in tables_created:
        print (i)
