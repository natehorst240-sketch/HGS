-- Wireshark dissector for the HGS <-> DAU serial download protocol
-- (reverse/PROTOCOL.md). Decodes captures made by sandbox/serialtap.py --pcap
-- or converted with sandbox/pcapng.py (link type USER0, one interface per
-- direction).
--
-- Install: copy or symlink this file into ~/.local/lib/wireshark/plugins/
-- (or ~/.config/wireshark/plugins/), or run
--     wireshark -X lua_script:sandbox/wireshark/hgs.lua capture.pcapng
-- Then the Protocol column reads HGS and each frame says which command,
-- ack or record type it is. Filter examples:  hgs.cmd == "DOWNLOAD LOGS"
--                                             hgs.record.type == "TIME HISTORY"
--                                             hgs.dir == "DAU->HGS"

local hgs = Proto("hgs", "HGS/DAU serial download")

local f_dir    = ProtoField.string("hgs.dir",         "Direction")
local f_kind   = ProtoField.string("hgs.kind",        "Kind")
local f_cmd    = ProtoField.string("hgs.cmd",         "Command / status")
local f_rtype  = ProtoField.string("hgs.record.type", "Record type")
local f_rlen   = ProtoField.uint32("hgs.record.len",  "Record length")
local f_label  = ProtoField.string("hgs.record.label","Record label")
local f_seq    = ProtoField.uint16("hgs.record.seq",  "Sequence id", base.DEC)
local f_data   = ProtoField.bytes ("hgs.data",        "Payload")
hgs.fields = { f_dir, f_kind, f_cmd, f_rtype, f_rlen, f_label, f_seq, f_data }

local MSG_LEN = 25
local f_ifid = Field.new("frame.interface_id")
-- 25-byte space-padded ASCII tokens known from the binary's string table
local COMMANDS = {
  ["DOWNLOAD LOGS"]=true, ["DOWNLOAD CUMULATIVE"]=true, ["DOWNLOAD STATUS"]=true,
  ["TRANSMISSION OK"]=true, ["RETRANSMIT"]=true, ["STAND BY READY"]=true,
  ["READY TO UPLOAD"]=true, ["UPLOAD DATA"]=true, ["COPY_FILES"]=true,
  ["DELETE_FILES"]=true, ["TRANSFER_FILES"]=true,
}
-- record sizes seen on the wire (PROTOCOL.md)
local RECORD_TYPES = {
  [110]  = "EXCEEDANCE PARAMETER",
  [92]   = "DISCRETE EVENT COUNTER",
  [228]  = "CUMULATIVE LOG",
  [2817] = "TIME HISTORY",
  [503]  = "POWER ASSURANCE LOG",
}

local function printable(s)
  return (s:gsub("[^%g ]", "."))
end

local function is_ascii_padded(tvb)
  if tvb:len() ~= MSG_LEN then return false end
  local s = tvb:raw()
  if not s:match("^[%w%p ][%w%p ]*$") then return false end
  return s:sub(-1) == " " or #s:gsub(" +$", "") < MSG_LEN
end

function hgs.dissector(tvb, pinfo, tree)
  local len = tvb:len()
  if len == 0 then return 0 end
  pinfo.cols.protocol = "HGS"

  -- direction from the pcapng interface id (0 = program/HGS, 1 = device/DAU)
  local dir = "?"
  local ifid = f_ifid()
  if ifid ~= nil then
    dir = (ifid.value == 0) and "HGS->DAU" or "DAU->HGS"
  end
  pinfo.cols.src = (dir == "DAU->HGS") and "DAU" or "HGS"
  pinfo.cols.dst = (dir == "DAU->HGS") and "HGS" or "DAU"

  local t = tree:add(hgs, tvb(), "HGS/DAU serial download")
  t:add(f_dir, dir)

  if is_ascii_padded(tvb) then
    local token = tvb:raw():gsub(" +$", "")
    local known = COMMANDS[token]
    t:add(f_kind, known and "control message" or "25-byte text (unknown token)")
    t:add(f_cmd, tvb(0, MSG_LEN), token)
    pinfo.cols.info = token .. (known and "" or "  [unlisted token]")
    return len
  end

  -- otherwise a stored record streamed by the DAU
  local rtype = RECORD_TYPES[len] or ("UNKNOWN (" .. len .. " bytes)")
  t:add(f_kind, "record")
  t:add(f_rtype, rtype)
  t:add(f_rlen, len)
  local info = rtype
  if len >= MSG_LEN then
    local head = tvb(0, MSG_LEN):raw()
    if head:match("^[%g ]+$") then
      local label = head:gsub(" +$", "")
      t:add(f_label, tvb(0, MSG_LEN), label)
      info = info .. "  \"" .. printable(label) .. "\""
    end
  end
  if (len == 110 or len == 92) and len >= 2 then
    -- trailing uint16 big-endian sequence id (FORMAT.md)
    t:add(f_seq, tvb(len - 2, 2))
  end
  t:add(f_data, tvb())
  pinfo.cols.info = info
  return len
end

-- bind to the pcapng link type our capture files use
local encap = DissectorTable.get("wtap_encap")
encap:add(wtap.USER0, hgs)
