import AppKit
import Foundation
let root = URL(fileURLWithPath: CommandLine.arguments[1])
let resources = root.appendingPathComponent("Paper Inbox.app/Contents/Resources")
let iconset = root.appendingPathComponent("cache/AppIcon.iconset")
try FileManager.default.createDirectory(at: iconset, withIntermediateDirectories: true)
func color(_ r: CGFloat, _ g: CGFloat, _ b: CGFloat) -> NSColor { NSColor(srgbRed:r, green:g, blue:b, alpha:1) }
func path(_ points: [NSPoint], close: Bool = false) -> NSBezierPath {
 let p = NSBezierPath();p.move(to:points[0]);for v in points.dropFirst(){p.line(to:v)};if close {p.close()};return p
}
func png(_ size: Int, menu: Bool = false) -> Data {
 let rep=NSBitmapImageRep(bitmapDataPlanes:nil,pixelsWide:size,pixelsHigh:size,bitsPerSample:8,samplesPerPixel:4,hasAlpha:true,isPlanar:false,colorSpaceName:.deviceRGB,bytesPerRow:0,bitsPerPixel:0)!
 let context=NSGraphicsContext(bitmapImageRep:rep)!
 NSGraphicsContext.saveGraphicsState();NSGraphicsContext.current=context
 let t=NSAffineTransform();t.scale(by:CGFloat(size)/1024);t.concat()
 if menu {
  NSColor.black.setStroke()
  let p=NSBezierPath(roundedRect:NSRect(x:260,y:330,width:504,height:548),xRadius:42,yRadius:42);p.lineWidth=64;p.stroke()
  let tray=path([NSPoint(x:140,y:480),NSPoint(x:140,y:150),NSPoint(x:884,y:150),NSPoint(x:884,y:480)])
  tray.lineWidth=70;tray.lineJoinStyle = .round;tray.lineCapStyle = .round;tray.stroke()
  for y in [650,510] {let l=path([NSPoint(x:375,y:y),NSPoint(x:645,y:y)]);l.lineWidth=56;l.lineCapStyle = .round;l.stroke()}
 } else {
  let bg=NSBezierPath(roundedRect:NSRect(x:64,y:64,width:896,height:896),xRadius:204,yRadius:204)
  NSShadow().set()
  NSGradient(starting:color(0.20,0.46,0.43),ending:color(0.055,0.23,0.23))!.draw(in:bg,angle: -65)
  // A rear sheet gives the mark a quiet sense of a daily collection.
  color(0.64,0.79,0.72).setFill();NSBezierPath(roundedRect:NSRect(x:306,y:305,width:452,height:500),xRadius:32,yRadius:32).fill()
  let sheet=path([NSPoint(x:264,y:305),NSPoint(x:264,y:820),NSPoint(x:604,y:820),NSPoint(x:704,y:720),NSPoint(x:704,y:305)],close:true)
  color(0.98,0.97,0.90).setFill();sheet.fill()
  color(0.76,0.83,0.76).setFill();path([NSPoint(x:604,y:820),NSPoint(x:604,y:720),NSPoint(x:704,y:720)],close:true).fill()
  for (y,w) in [(655,236),(576,284),(497,194)] {
   color(0.25,0.43,0.40).setFill();NSBezierPath(roundedRect:NSRect(x:335,y:y,width:w,height:23),xRadius:11.5,yRadius:11.5).fill()
  }
  // Open tray: pale rim and a darker front with a centered paper notch.
  color(0.40,0.66,0.59).setFill();path([NSPoint(x:191,y:368),NSPoint(x:255,y:469),NSPoint(x:769,y:469),NSPoint(x:833,y:368)],close:true).fill()
  let front=NSBezierPath();front.move(to:NSPoint(x:191,y:368));front.line(to:NSPoint(x:408,y:368));front.curve(to:NSPoint(x:450,y:313),controlPoint1:NSPoint(x:420,y:368),controlPoint2:NSPoint(x:420,y:313));front.line(to:NSPoint(x:574,y:313));front.curve(to:NSPoint(x:616,y:368),controlPoint1:NSPoint(x:604,y:313),controlPoint2:NSPoint(x:604,y:368));front.line(to:NSPoint(x:833,y:368));front.line(to:NSPoint(x:833,y:236));front.curve(to:NSPoint(x:791,y:194),controlPoint1:NSPoint(x:833,y:210),controlPoint2:NSPoint(x:817,y:194));front.line(to:NSPoint(x:233,y:194));front.curve(to:NSPoint(x:191,y:236),controlPoint1:NSPoint(x:207,y:194),controlPoint2:NSPoint(x:191,y:210));front.close()
  NSGradient(starting:color(0.79,0.88,0.77),ending:color(0.48,0.69,0.59))!.draw(in:front,angle: -90)
 }
 NSGraphicsContext.restoreGraphicsState();return rep.representation(using:.png,properties:[:])!
}
for n in [16,32,128,256,512] {
 try png(n).write(to:iconset.appendingPathComponent("icon_\(n)x\(n).png"))
 try png(n*2).write(to:iconset.appendingPathComponent("icon_\(n)x\(n)@2x.png"))
}
try png(1024).write(to:root.appendingPathComponent("assets/AppIcon.png"))
try png(36,menu:true).write(to:resources.appendingPathComponent("MenuBarIcon.png"))
