import { useEffect, useId } from 'react';

export const meaningLabels: Record<string,string> = {
 ON_HAND_INVENTORY:'On-hand stock', REMAINING_LOCAL_REQUIREMENT:'Still required for local work',
 OUTSTANDING_DEMAND:'Uncovered need', CONFIRMED_SURPLUS:'Released surplus', POTENTIAL_SURPLUS:'Potential excess',
 PLANNED_REQUIREMENT:'Planned requirement', PURCHASE_ORDER:'Ordered supply', RECEIPT:'Received quantity', UNKNOWN:'Technical / contextual information',
};
export const unitName = (unit: string) => ({pcs:'pieces',m2:'m²',m3:'m³',kg:'kg',m:'metres'}[unit] || unit);
export const normalUnit = (value:string) => ({'m²':'m2','m^2':'m2','m³':'m3','m^3':'m3',pieces:'pcs',piece:'pcs',pc:'pcs',bags:'bag',metres:'m',meters:'m',kilograms:'kg',tonnes:'tonne'}[value.trim().toLowerCase()] || value.trim().toLowerCase());
export type SpecEntry = {name:string;value:string};
export const specificationEntries = (value: Record<string,unknown>): SpecEntry[] => Object.entries(value).map(([name,v])=>({name,value:String(v??'')}));
export function specificationObject(rows: SpecEntry[]):Record<string,string> {
 const result:Record<string,string>={};
 for(const row of rows){if(!row.name.trim()){if(row.value)throw new Error('Give each specification a name, or remove the empty row.');continue;}
  if(Object.hasOwn(result,row.name))throw new Error(`Specification “${row.name}” appears twice. Use a different name or remove the duplicate.`);
  Object.defineProperty(result,row.name,{value:row.value,enumerable:true,configurable:true,writable:true});
 }
 return result;
}
export function SpecificationFields({rows,onChange}:{rows:SpecEntry[];onChange:(rows:SpecEntry[])=>void}){
 const id=useId();return <div className="material-specifications">
 {rows.map((row,i)=><div className="material-spec-row" key={i}><label htmlFor={`${id}-name-${i}`}>Attribute<input id={`${id}-name-${i}`} value={row.name} onChange={e=>onChange(rows.map((r,j)=>i===j?{...r,name:e.target.value}:r))}/></label><label htmlFor={`${id}-value-${i}`}>Value<input id={`${id}-value-${i}`} value={row.value} onChange={e=>onChange(rows.map((r,j)=>i===j?{...r,value:e.target.value}:r))}/></label><button type="button" aria-label={`Remove specification ${row.name||i+1}`} onClick={()=>onChange(rows.filter((_,j)=>j!==i))}>Remove</button></div>)}
 <button type="button" className="material-text-action" onClick={()=>onChange([...rows,{name:'',value:''}])}>Add a specification</button></div>;
}
export function beforeEditorNavigation(){return window.dispatchEvent(new Event('terra:before-editor-navigation',{cancelable:true}));}
export function useUnsavedMaterialForm(dirty:boolean){
 useEffect(()=>{if(!dirty)return;const unload=(e:BeforeUnloadEvent)=>{e.preventDefault();e.returnValue='';};
 const navigate=(e:Event)=>{if(!window.confirm('Discard your unsaved form changes?'))e.preventDefault();};
 window.addEventListener('beforeunload',unload);window.addEventListener('terra:before-editor-navigation',navigate);
 return()=>{window.removeEventListener('beforeunload',unload);window.removeEventListener('terra:before-editor-navigation',navigate);};},[dirty]);
}
