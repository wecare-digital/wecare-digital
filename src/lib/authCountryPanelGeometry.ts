/** Keep the fixed country picker inside the visual viewport, including a
 * narrowed or panned viewport above a mobile software keyboard. */
export interface AuthCountryPanelInput {
  layoutWidth: number;
  layoutHeight: number;
  viewportLeft: number;
  viewportTop: number;
  viewportWidth: number;
  viewportHeight: number;
  anchor: { left: number; right: number; top: number; bottom: number };
  rtl: boolean;
}

export function authCountryPanelGeometry(input: AuthCountryPanelInput) {
  const {layoutWidth,layoutHeight,viewportLeft,viewportTop,viewportWidth,viewportHeight,anchor,rtl}=input;
  const gutterX=Math.min(viewportWidth<360?10:16,viewportWidth/8);
  const gutterY=Math.min(12,viewportHeight/8);
  const leftEdge=viewportLeft+gutterX;
  const rightEdge=viewportLeft+viewportWidth-gutterX;
  const topEdge=viewportTop+gutterY;
  const bottomEdge=viewportTop+viewportHeight-gutterY;
  const narrow=layoutWidth<=767||viewportWidth<=767;
  const width=Math.max(0,Math.min(narrow?460:360,rightEdge-leftEdge));
  const wantedLeft=narrow?leftEdge+(rightEdge-leftEdge-width)/2:rtl?anchor.right-width:anchor.left;
  const left=Math.max(leftEdge,Math.min(wantedLeft,rightEdge-width));
  const available=Math.max(0,bottomEdge-topEdge);
  const cap=Math.min(narrow?460:360,available);
  const below=bottomEdge-Math.max(topEdge,anchor.bottom+8);
  const above=Math.min(bottomEdge,anchor.top-8)-topEdge;
  if(narrow||Math.max(below,above)<Math.min(180,cap)){
    return {left,width,bottom:layoutHeight-bottomEdge,maxHeight:cap};
  }
  if(below>=Math.min(220,cap)||below>=above){
    const top=Math.max(topEdge,anchor.bottom+8);
    return {left,width,top,maxHeight:Math.max(0,Math.min(cap,bottomEdge-top))};
  }
  const bottom=Math.min(bottomEdge,anchor.top-8);
  return {left,width,bottom:layoutHeight-bottom,maxHeight:Math.max(0,Math.min(cap,bottom-topEdge))};
}
