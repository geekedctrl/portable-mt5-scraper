(function(root){
  root.ChartPaging={
    mergeOlder(current,incoming){const byTime=new Map(current.map(bar=>[bar.time,bar]));for(const bar of incoming)byTime.set(bar.time,bar);return [...byTime.values()].sort((a,b)=>a.time-b.time)},
    preserveAnchor(start,added){return start+added},
    dragDelta(previous,current){return current-previous},
    wheelDelta(deltaX,ctrlKey){return ctrlKey?0:deltaX},
    endGesture(gesture,pointerId){return gesture&&gesture.id!==pointerId?gesture:null},
    needsOlder(start,limit,hasOlder){return !!hasOlder&&start<=Math.ceil(limit*.2)}
  };
})(typeof window==='undefined'?globalThis:window);
