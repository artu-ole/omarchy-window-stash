#!/usr/bin/env python3
"""Exercise preview/icon stages and real icon controls without desktop input."""
import os
from pathlib import Path
import shutil
import subprocess
import tempfile

ROOT=Path(__file__).resolve().parents[1]
with tempfile.TemporaryDirectory(prefix='stash-preview-folding-') as directory:
    folder=Path(directory)
    shutil.copytree(ROOT/'ui',folder/'ui')
    for name in ('Commons','Ui'):
        (folder/name).symlink_to('/usr/share/omarchy/shell/'+name,target_is_directory=True)
    for name in ('runtime','cache','config'):
        (folder/name).mkdir(mode=0o700)
    (folder/'ui/StashPreviewImage.qml').write_text('''import QtQuick
Item {
  property var stash
  property var record
  property string mode:"still"
  property bool active:false
  property string animations:"off"
  property string animationSpeed:"normal"
  property size sourceSize:Qt.size(640,420)
  readonly property bool eligible:active
  readonly property bool hasContent:active
  function contentRect() {return {x:0,y:0,width:width,height:height}}
  function details() {return {captureActive:active,hasContent:hasContent,live:active && mode==="live"}}
}
''')
    (folder/'shell.qml').write_text('''pragma ComponentBehavior: Bound
import QtQuick
import QtQuick.Window
import Quickshell
import "ui"

ShellRoot {
  id:root
  property int phase:0
  property int ticks:0
  property var first:({id:"first",address:"0x1",pid:10,stableId:"a",tag:"owned-a",phase:"stashed",app:"test",title:"First",size:[640,420],fullscreen:2})
  property var second:({id:"second",address:"0x2",pid:11,stableId:"b",tag:"owned-b",phase:"stashed",app:"test",title:"Second",size:[640,420]})
  property var target:null
  property var remembered:null
  property var moved:null
  property bool grouped:false
  QtObject {
    id:fake
    property var saved:({"preview:window:a":[180,150,360,1.4]})
    property var pendingCloseIds:({})
    property var pendingPreviewFoldIds:({})
    property bool lifecycleReady:true
    property var previewInteractionRequest:null
    property var previewInteractionPendingRequest:null
    property var previewInteractionStatus:({state:"idle"})
    property string previewInteractionError:""
    property bool pointerKnown:false
    property point pointerPosition:Qt.point(0,0)
    property var writes:[]
    property var unfolded:[]
    property string restored:""
    property var closed:[]
    property var context:[]
    signal pointerClicked(real x,real y,int button)
    signal snapshotChanged()
    function screenMonitor(screen) {return {name:screen,x:-1600,y:40}}
    function groupClosing(group) {return false}
    function positionPending(key) {return false}
    function recordPreviewPosition(m,key,x,y,width,aspect) {
      var point=[x,y,width];if(aspect>0) point.push(aspect)
      var next=Object.assign({},saved);next[key]=point;saved=next;writes=writes.concat([{key:key,point:point}])
    }
    function recordPosition(m,key,x,y) {var next=Object.assign({},saved);next[key]=[x,y];saved=next;writes=writes.concat([{key:key,point:[x,y]}])}
    function restorePreviewWindow(id,screen) {restored=id}
    function unfoldPreviewWindows(windows,screen) {unfolded=windows.map(function(record) {return record.id})}
    function closeGroup(group,screen) {closed=group.windows.map(function(record) {return record.id})}
    function closeWindows(windows,screen) {closed=windows.map(function(record) {return record.id})}
    function openContext(group,screen,point) {context=group.windows.map(function(record) {return record.id})}
    function endPreviewInteraction() {previewInteractionRequest=null}
    function beginPreviewInteraction() {throw new Error("A folded source acquired native input")}
  }
  Window {
    id:window;width:1280;height:800;visible:true
    StashFloatingPreviews {
      id:previews;stash:fake
      config:({presentation:"previews",animations:"off",animationSpeed:"normal",floatingPlacement:"free",dragMotion:"direct",sizePreset:"100",iconShape:"squircle",iconFrame:"hidden",iconOpacity:60,floatingPreviewSizing:"free",floatingPreviewUpdate:"live",floatingPreviewTitles:"hidden",floatingPreviewFrame:"hidden",floatingPreviewLock:"unlocked",floatingPreviewInteraction:"on",floatingPreviewActivation:"explicit"})
      area:({x:0,y:26,width:1280,height:774});coordinateRoot:window.contentItem;screenName:"test";monitor:({x:-1600,y:40})
      savedPositions:fake.saved;groups:[{key:"window:a",app:"test",windows:[root.first]}];active:true
    }
  }
  function check(value,message) {if(!value) throw new Error(message)}
  function near(a,b,message) {check(Math.abs(a-b)<1,message+": "+a+" vs "+b)}
  function same(a,b,message) {check(JSON.stringify(a)===JSON.stringify(b),message)}
  function card() {return previews.cardList().find(function(item) {return !item.retiring})}
  function icon() {return previews.foldedIconList().find(function(item) {return !item.retiring})}
  function setting(key,value) {var next=Object.assign({},previews.config);next[key]=value;previews.config=next}
  function update() {previews.groups=grouped ? [{key:"app:test",app:"test",windows:[first,second]}] : [{key:"window:a",app:"test",windows:[first]}]}
  function fold(value) {first=Object.assign({},first,{previewFolded:value});update()}
  function pointer(item) {var rect=item.nativeImageRect();return {x:rect.x+rect.width*.4,y:rect.y+rect.height*.7}}
  function captures() {return previews.cardList().concat(previews.tileList()).filter(function(item) {return item.details().image.captureActive})}
  Timer {
    interval:35;repeat:true;running:true
    onTriggered: {
      try {
        check(++root.ticks<150,"Folded preview UI did not settle")
        if(root.phase===0) {
          check(card() && !icon(),"Initial preview was not a full card")
          remembered={x:card().x,y:card().y,width:card().width,height:card().height,aspect:card().aspectOverride}
          var at=pointer(card());target=previews.foldAt(at.x,at.y)
          same(target.ids,["first"],"Fresh global pointer did not select the exact preview")
          check(target.key==="folded-preview:window:a" && target.screenName==="test","Fold descriptor lost stable icon/screen ownership")
          fake.pendingPreviewFoldIds={first:true}
          same(previews.foldAt(at.x,at.y).ids,[],"Pending fold fell through to the real window")
          fake.pendingPreviewFoldIds={}
          previews.prepareFold(target.key,target.origin);fold(true)
        } else if(root.phase===1) {
          check(!card() && !!icon() && previews.present,"All-folded presentation disappeared")
          check(captures().length===0,"Folding retained a client capture")
          check(previews.inputRegions.length===1,"Folded icon was omitted from the input mask")
          same(previews.details().folded.icons[0].recordIds,["first"],"Folded icon lost its exact source")
          near(icon().x,remembered.x+(remembered.width-icon().width)/2,"Icon did not originate at the preview center")
          near(icon().y,remembered.y+(remembered.height-icon().height)/2,"Icon did not originate at the preview center")
          same(fake.saved["preview:window:a"],[180,150,360,1.4],"Folding overwrote preview dimensions or custom ratio")
          var gx=-1600+icon().x+icon().width/2,gy=40+icon().y+icon().height/2
          same(previews.foldAt(gx,gy).ids,[],"Already-folded hover could minimize the window behind")
          check(!previews.handleActivationShortcut(1,"press",gx,gy),"Super-click fell through a folded icon")
          check(!icon().frameVisible && icon().iconShape==="squircle" && !icon().previewEnabled,"Folded icon ignored appearance or acquired hover capture")
          icon().dragHeld(true);icon().moved(65,45);icon().dragHeld(false);icon().dragFinished()
        } else if(root.phase===2) {
          moved=[icon().x,icon().y]
          near(moved[0],target.origin.x+(target.origin.width-icon().width)/2+65,"Folded icon could not move")
          near(moved[1],target.origin.y+(target.origin.height-icon().height)/2+45,"Folded icon could not move")
          same(fake.saved[target.key].map(Math.round),moved.map(Math.round),"Folded icon position was not saved separately")
          icon().activated()
          same(fake.unfolded,["first"],"Icon activation did not request the preview stage")
          check(!fake.restored,"Icon activation restored the full window")
          fold(false)
        } else if(root.phase===3) {
          check(card() && !icon() && captures().length===1,"Unfold did not restore exactly one preview capture")
          near(card().x,remembered.x,"Unfold lost preview position");near(card().y,remembered.y,"Unfold lost preview position")
          near(card().width,remembered.width,"Unfold lost preview width");near(card().height,remembered.height,"Unfold lost preview height")
          near(card().aspectOverride,remembered.aspect,"Unfold lost preview proportions")
          same(first.size,[640,420],"Visual folding modified original restoration geometry")
          check(first.fullscreen===2,"Folding changed saved fullscreen state")
          card().activated();check(fake.restored==="first","The next preview activation did not restore the full window")
          fake.restored="";fold(true)
        } else if(root.phase===4) {
          near(icon().x,moved[0],"Re-fold lost the independent icon placement")
          near(icon().y,moved[1],"Re-fold lost the independent icon placement")
          icon().contextRequested(10,10);same(fake.context,["first"],"Folded context menu lost its exact window")
          icon().closeRequested();same(fake.closed,["first"],"Folded middle-close route lost its exact window")
          setting("floatingPreviewLock","locked");check(!icon().draggable,"Locked preview placement left folded icons draggable")
          icon().activated();same(fake.unfolded,["first"],"Lock prevented unfolding")
          setting("floatingPreviewLock","unlocked")
          grouped=true;first=Object.assign({},first,{previewFolded:false});second=Object.assign({},second,{previewFolded:true});update()
        } else if(root.phase===5) {
          check(card().group.windows.length===1 && icon().group.windows.length===1,"App grouping mixed folded and preview records")
          same(card().group.windows.map(function(record) {return record.id}),["first"],"Visible app cover still contains a folded source")
          same(icon().group.windows.map(function(record) {return record.id}),["second"],"Folded app icon contains an unfolded source")
          var at=pointer(card());same(previews.foldAt(at.x,at.y).ids,["first"],"Cover fold included already folded app members")
          second=Object.assign({},second,{previewFolded:false});update()
        } else if(root.phase===6) {
          var at=pointer(card());target=previews.foldAt(at.x,at.y)
          same(target.ids,["first","second"],"App cover did not represent its whole visible group")
          card().activatePrimary()
        } else if(root.phase===7) {
          check(previews.expanded && previews.tileList().length===2,"App cover did not offer exact-window tiles")
          var tile=previews.tileList().find(function(item) {return item.record.id==="second"}),at=pointer(tile)
          target=previews.foldAt(at.x,at.y);same(target.ids,["second"],"Expanded tile folding selected siblings")
          check(target.key==="folded-preview:app:test","Expanded app tile used a conflicting icon grouping key")
          first=Object.assign({},first,{previewFolded:true});second=Object.assign({},second,{previewFolded:true});update()
        } else if(root.phase===8) {
          check(!card() && !previews.expanded && icon().group.windows.length===2,"Grouped folded records created duplicate lists")
          check(captures().length===0,"Grouped folding retained source captures")
          icon().activated();same(fake.unfolded,["first","second"],"Grouped icon failed to unfold its represented windows")
          first=Object.assign({},first,{previewFolded:"true"});second=Object.assign({},second,{previewFolded:false});update()
        } else if(root.phase===9) {
          check(card() && !icon(),"Nonboolean folded data hid a preview")
          previews.active=false
        } else if(root.phase===10) {
          check(previews.inputRegions.length===0 && !previews.held && captures().length===0,"Disabling presentation left folded input or captures")
          check(previews.details().folded.world.bodies.length===0,"Disabling folded icons leaked physics bodies")
          grouped=false;first=Object.assign({},first,{previewFolded:false});setting("animations","full");update();previews.active=true
          root.ticks=0
        } else if(root.phase===11) {
          if(!card() || card().presence<.999) return
          var at=pointer(card());target=previews.foldAt(at.x,at.y);previews.prepareFold(target.key,target.origin)
          fold(true);root.ticks=0
        } else if(root.phase===12) {
          var retiring=previews.cardList().find(function(item) {return item.retiring})
          check(!!retiring && retiring.folding && retiring.presence>0 && retiring.presence<1,"Fold animation skipped its intermediate source state: "+JSON.stringify(previews.cardList().map(function(item) {return {retiring:item.retiring,folding:item.folding,presence:item.presence,scale:item.scale,animations:item.animations}})))
          check(retiring.scale>0 && retiring.scale<.99 && !retiring.details().image.captureActive,"Fold animation either jumped or retained capture")
          check(icon() && icon().presence>0 && icon().presence<1,"Icon did not crossfade during folding")
        } else if(root.phase===13) {
          fold(false);root.ticks=0
        } else if(root.phase===14) {
          check(card() && card().unfolding && card().presence>0 && card().presence<1,"Unfold animation skipped its intermediate preview state")
          check(!card().interactionReady(false),"An unfolding preview acquired input while translating or growing")
        } else if(root.phase===15) {
          if(!card() || card().presence<.999) return
          near(card().width,remembered.width,"Animation changed the remembered preview size")
          fold(true);root.ticks=0
        } else if(root.phase===16) {
          if(!icon() || icon().presence<.999) return
          setting("floatingPlacement","edges");root.ticks=0
        } else if(root.phase===17) {
          var state=previews.details().folded,body=state.world.bodies[0]
          if(body && body.moving) return
          var r=state.icons[0],area=previews.area
          check(Math.min(Math.abs(r.x-area.x-8),Math.abs(r.x+r.width-area.x-area.width+8),
            Math.abs(r.y-area.y-8),Math.abs(r.y+r.height-area.y-area.height+8))<1.1,"Folded icon ignored edge gravity")
          same(fake.saved["preview:window:a"],[180,150,360,1.4],"Animation or gravity overwrote preview geometry")
          setting("animations","off");previews.active=false
        } else if(root.phase===18) {
          check(!previews.held && previews.inputRegions.length===0,"Final animation cleanup retained an input grab")
          console.log("PREVIEW_FOLDING_QT_PASS");Qt.quit()
        }
        root.phase++
      } catch(error) {console.error("PREVIEW_FOLDING_QT_FAIL: "+error);Qt.exit(1)}
    }
  }
}
''')
    env=dict(os.environ,QT_QPA_PLATFORM='offscreen',QT_QPA_PLATFORMTHEME='generic',
             QT_QUICK_CONTROLS_STYLE='Basic',QSG_RHI_BACKEND='software',
             XDG_RUNTIME_DIR=str(folder/'runtime'),XDG_CACHE_HOME=str(folder/'cache'),
             XDG_CONFIG_HOME=str(folder/'config'),DBUS_SESSION_BUS_ADDRESS='unix:path=/dev/null')
    for name in ('WAYLAND_DISPLAY','DISPLAY','HYPRLAND_INSTANCE_SIGNATURE'):
        env.pop(name,None)
    result=subprocess.run(['qs','-p',str(folder/'shell.qml')],env=env,capture_output=True,text=True,timeout=10)
    output=result.stdout+result.stderr
    assert result.returncode==0 and 'PREVIEW_FOLDING_QT_PASS' in output,output
    assert not any(value in output for value in ('Binding loop','ReferenceError','TypeError','Cannot assign','Cannot read')),output
    print('Qt preview folding: exact hover targets, paused capture, independent draggable icon placement, staged activation, grouping, shape memory and lifecycle passed')
