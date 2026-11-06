.pragma library

// A window address can be reused. Match the ledger's ownership identity as
// well as its address before handing a native toplevel to the capture view.
function address(value) {
  if (typeof value !== "string" || !/^(?:0x)?[0-9a-f]+$/i.test(value)) return ""
  var normalized=value.replace(/^0x/i, "").replace(/^0+/, "").toLowerCase()
  return normalized && normalized!=="0" ? normalized : ""
}

function stableId(value) {
  if (typeof value === "number") {
    if (!Number.isSafeInteger(value) || value<0) return ""
    return value.toString(16)
  }
  if (typeof value !== "string" || !/^(?:0x)?[0-9a-f]+$/i.test(value)) return ""
  return value.replace(/^0x/i, "").replace(/^0+(?=.)/, "").toLowerCase()
}

function validRecord(record) {
  return !!record && typeof record.id==="string" && record.id.length>0
    && address(record.address)!=="" && Number.isSafeInteger(record.pid) && record.pid>0
    && record.tag==="window-stash-"+record.id && record.phase==="stashed"
    && (!record.stableId || stableId(record.stableId)!=="")
}

function key(record) {
  if (!record) return ""
  return JSON.stringify([record.id, address(record.address), record.pid,
    record.stableId ? stableId(record.stableId) : "", record.tag, record.phase])
}

function hasTag(tags, wanted) {
  // Native QVariantLists are QML sequences, not JavaScript Array instances.
  // Index exact entries rather than using string/substring membership.
  if (!tags || typeof tags!=="object" || !Number.isSafeInteger(tags.length)
      || tags.length<0 || tags.length>4096) return false
  for (var i=0;i<tags.length;i++) if (tags[i]===wanted) return true
  return false
}

function matches(record, client) {
  return validRecord(record) && !!client && address(client.address)===address(record.address)
    && client.mapped===true && client.pid===record.pid
    && (!record.stableId || stableId(client.stableId)===stableId(record.stableId))
    && !!client.workspace && client.workspace.name==="special:minimized"
    && hasTag(client.tags,record.tag)
}

function findClient(record, clients) {
  if (!validRecord(record) || !Array.isArray(clients)) return null
  var matchingAddress=clients.filter(function(client) {
    return !!client && address(client.address)===address(record.address)
  })
  return matchingAddress.length===1 && matches(record,matchingAddress[0]) ? matchingAddress[0] : null
}
