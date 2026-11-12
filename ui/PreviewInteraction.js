.pragma library

// Input geometry is in compositor-global logical coordinates. Texture pixels,
// monitor scaling and the card's optional title strip never enter this mapping.
function validRect(rect) {
  return !!rect && [rect.x,rect.y,rect.width,rect.height].every(function(value) {
    return typeof value==="number" && Number.isFinite(value)
  }) && rect.width>0 && rect.height>0
}
function rectCopy(rect) {return {x:rect.x,y:rect.y,width:rect.width,height:rect.height}}
function intersection(first,second) {
  if(!validRect(first) || !validRect(second)) return null
  var x=Math.max(first.x,second.x),y=Math.max(first.y,second.y)
  var right=Math.min(first.x+first.width,second.x+second.width),bottom=Math.min(first.y+first.height,second.y+second.height)
  return right>x && bottom>y ? {x:x,y:y,width:right-x,height:bottom-y} : null
}
function controlsPlacement(image,area,width,height) {
  if(!validRect(image) || !validRect(area) || width<=0 || height<=0) return null
  function clamp(value,low,high) {return Math.max(low,Math.min(high,value))}
  var x=clamp(image.x+image.width-width,area.x,area.x+area.width-width)
  var y=clamp(image.y,area.y,area.y+area.height-height),gap=5
  var candidates=[{x:x,y:image.y-height-gap,width:width,height:height},
    {x:x,y:image.y+image.height+gap,width:width,height:height},
    {x:image.x-width-gap,y:y,width:width,height:height},
    {x:image.x+image.width+gap,y:y,width:width,height:height}]
  for(var index=0;index<candidates.length;index++) {
    var rect=candidates[index]
    if(rect.x>=area.x && rect.y>=area.y && rect.x+width<=area.x+area.width && rect.y+height<=area.y+area.height
        && !intersection(rect,image)) return rect
  }
  return null
}
function exclusions(image,overlays,clip) {
  if(!validRect(image)) return []
  var values=[]
  ;(overlays || []).forEach(function(overlay) {
    var rect=intersection(image,overlay)
    if(rect) values.push(rect)
  })
  if(clip && validRect(clip)) {
    var visible=intersection(image,clip)
    if(!visible) return [rectCopy(image)]
    if(visible.x>image.x) values.push({x:image.x,y:image.y,width:visible.x-image.x,height:image.height})
    if(visible.x+visible.width<image.x+image.width) values.push({x:visible.x+visible.width,y:image.y,width:image.x+image.width-visible.x-visible.width,height:image.height})
    if(visible.y>image.y) values.push({x:image.x,y:image.y,width:image.width,height:visible.y-image.y})
    if(visible.y+visible.height<image.y+image.height) values.push({x:image.x,y:visible.y+visible.height,width:image.width,height:image.y+image.height-visible.y-visible.height})
  }
  return values.slice(0,16)
}
function enabled(settings) {return !!settings && settings.presentation==="previews" && settings.floatingPreviewInteraction==="on"}
function matches(request,id,monitor,key) {
  return !!request && request.id===id && request.monitor===monitor && (key===undefined || request.viewKey===key)
}
function request(serial,id,monitor,key,rect,excludeRects,settings) {
  if(!enabled(settings) || !Number.isInteger(serial) || serial<=0 || serial>2147483647 || typeof id!=="string" || !id
      || typeof monitor!=="string" || !monitor || !validRect(rect)) return null
  return {serial:serial,id:id,monitor:monitor,viewKey:key,rect:rectCopy(rect),
    excludeRects:(excludeRects || []).filter(validRect).slice(0,16).map(rectCopy),
    keyboard:settings.floatingPreviewKeyboard==="click",fps:settings.floatingPreviewInteractionFps==="30" ? 30 : 60}
}
function wire(request) {
  if(!request) return null
  return {serial:request.serial,id:request.id,monitor:request.monitor,rect:request.rect,
    excludeRects:request.excludeRects,keyboard:request.keyboard,fps:request.fps}
}
