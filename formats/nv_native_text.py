"""Read simple native text blocks without treating them as image placeholders.

Supports a single InsertString and whole-block formatting, as in Python.ntb.
The original events remain the authority for saving, never the rendered text.
"""
import struct
import formats.nv_ntb as n


def text_records(events,b,page_indices=None):
    blocks={};strings={};styles={}
    for _,e in events:
        typ=b.data[e.field(4)] if e.field(4) else -1
        p=n.payload_table(b,e)
        if p is None:continue
        ref=e.field(0)
        if not ref or b.u32(ref):continue
        ident=b.u32(ref+4)
        if typ==22 and not p.field(0) and not p.field(10):
            if all(p.field(i) for i in (2,3,6)):
                page=n.field_u32(b,p,2,8)
                if page_indices:page=page_indices.get(n.field_u32(b,p,2,4))
                x,y=struct.unpack_from('<2f',b.data,p.field(3))
                w,h=struct.unpack_from('<2f',b.data,p.field(6))
                margins=(struct.unpack_from('<4f',b.data,p.field(19)) if p.field(19)
                         else (3.,10.,5.,5.))
                blocks[ident]=dict(page=page,x=x,y=y,width=w,height=h,event_id=ident,margins=margins)
        elif typ==8 and p.field(2) and not b.u32(p.field(2)):
            field=b.u32(p.field(2)+4)
            ptr=p.field(1)
            if ptr:
                v=ptr+b.u32(ptr);length=b.u32(v)
                if b.valid(v+4,length):
                    strings.setdefault(field,[]).append((bool(p.field(0)),b.data[v+4:v+4+length].decode('utf8')))
        elif typ==12 and p.field(2) and not b.u32(p.field(2)):
            field=b.u32(p.field(2)+4)
            style=styles.setdefault(field,{})
            size=n.child_table(b,p,8)
            if size and size.field(0):style['font_size']=b.f32(size.field(0))
            family=n.child_table(b,p,7)
            if family and family.field(0):
                v=family.field(0)+b.u32(family.field(0))
                if b.valid(v+4,b.u32(v)):style['font_family']=b.data[v+4:v+4+b.u32(v)].decode('utf8')
    records=[]
    layers=n.native_image_event_state(events,b)
    hidden=n.hidden_image_event_ids(events,b)
    for ident,block in blocks.items():
        entries=strings.get(ident,[])
        if ident in hidden or block['page'] is None or len(entries)!=1 or entries[0][0]:continue
        records.append(dict(block,text=entries[0][1],z_index=layers.get(ident,{}).get('z_index',0),**styles.get(ident,{})))
    return records
