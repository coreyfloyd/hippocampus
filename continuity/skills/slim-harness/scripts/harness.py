#!/usr/bin/env python3
"""Measure explicit session inputs and journal exact, individually reversible edits.

No semantic review, file discovery, generator execution, or git mutation occurs here.
"""
from __future__ import annotations

import argparse
from difflib import SequenceMatcher
import unicodedata
import json
from pathlib import Path
import re
import subprocess
import shlex
import sys


def size(text):
    return dict(lines=len(text.splitlines()), words=len(text.split()), bytes=len(text.encode('utf-8')))


def frontmatter(text):
    """Read scalar discovery fields, including quoted and block YAML strings.

Reject unsupported discovery-field syntax rather than silently undercount it.
"""
    lines=text.splitlines(keepends=True)
    if not lines or lines[0].strip() != '---':
        return {}, text
    end=next((i for i in range(1,len(lines)) if lines[i].strip()=='---'),None)
    if end is None:
        raise ValueError('unterminated skill frontmatter')
    fields={}; i=1
    while i < end:
        match=re.match(r'^(description|when_to_use):\s*(.*?)\s*$',lines[i])
        i+=1
        if not match:
            continue
        key,value=match.groups()
        if value not in ('|','|-','|+','>','>-','>+'):
            continuation=i
            while continuation < end and (not lines[continuation].strip()
                    or lines[continuation].lstrip().startswith('#')):
                continuation+=1
            if continuation < end and lines[continuation][0:1].isspace():
                raise ValueError('unsupported multiline skill discovery scalar: '+key)
        if value in ('|','|-','|+','>','>-','>+'):
            block=[]
            while i < end and (lines[i][0:1].isspace() or not lines[i].strip()):
                block.append(lines[i]); i+=1
            import textwrap
            value=textwrap.dedent(''.join(block))
            if match.group(2).startswith('>'):
                # YAML folds adjacent nonempty lines; blank lines retain paragraph breaks.
                value=re.sub(r'(?<=\S)\n(?=\S)', ' ', value)
            if match.group(2).endswith('-'):
                value=value.rstrip('\n')
            elif not match.group(2).endswith('+'):
                value=value.rstrip('\n')+'\n'
        elif value.startswith('"'):
            value=json.loads(value)
        elif value.startswith("'") and value.endswith("'"):
            value=value[1:-1].replace("''", "'")
        elif value.startswith(('[','{','&','*','!')):
            raise ValueError('unsupported skill discovery scalar: '+key)
        else:
            value=re.split(r'\s+#',value,maxsplit=1)[0]
        fields[key]=value
    return fields, ''.join(lines[end+1:])


def measure(manifest):
    """Only measure caller-attested loaded files; listed skills expose metadata only.

Kinds: rules, user-rules, skill, agent, role, output-style. The parent provides
role_paths from the actual definition and chain from root to session start.
"""
    tool=manifest['tool']
    if tool not in ('claude','codex'):
        raise ValueError('tool must be claude or codex')
    result=dict(over_limit=[], measured=[], unresolved=[])
    queue=list(manifest.get('files',[])); seen=set(); descriptions=[]; loaded_sizes={}
    while queue:
        item=queue.pop(0);loaded=item.get('loaded');kind=item['kind'];path=Path(item['path']).expanduser()
        if loaded not in ('full','auto','listed') or (loaded=='listed' and kind!='skill'):
            continue
        if kind=='output-style' and tool!='claude':
            continue
        if kind not in ('rules','user-rules','skill','agent','role','output-style'):
            raise ValueError('unsupported instruction kind: '+kind)
        key=(str(path.resolve()),kind,loaded)
        if key in seen:
            continue
        seen.add(key)
        if not path.is_file():
            result['unresolved'].append(str(path));continue
        text=path.read_bytes().decode('utf-8');stats=size(text);limits=[]
        if loaded!='listed':
            loaded_sizes[str(path.resolve())]=stats
            count=stats['lines'];limit=200;unit='lines'
            if kind=='skill':
                _,body=frontmatter(text);body_stats=size(body)
                count=body_stats['lines'];limit=500;unit='body lines'
                if body_stats['bytes']>20000:
                    limits.append(dict(unit='body bytes',measured=body_stats['bytes'],limit=20000))
            elif kind=='user-rules' and tool=='codex':
                count=stats['bytes'];limit=32768;unit='bytes'
            if count>limit:
                limits.append(dict(unit=unit,measured=count,limit=limit))
        if kind=='skill':
            fields,_=frontmatter(text);desc=fields.get('description','');when=fields.get('when_to_use','')
            stats['description_characters']=len(desc)
            descriptions.append(dict(path=str(path),characters=len(desc)))
            if len(desc)>1024:
                limits.append(dict(unit='description characters',measured=len(desc),limit=1024))
            if tool=='claude' and len(desc)+len(when)>1536:
                limits.append(dict(unit='description + when_to_use characters',measured=len(desc)+len(when),limit=1536))
        row=dict(path=str(path),source=str(path.resolve()),size=stats,limits=limits,
                 action='run /slim-harness on `'+str(path)+'`')
        # Listed-only bodies are not reported or used for size triggers.
        if loaded=='listed':
            row['size']=dict(description_characters=len(fields.get('description','')))
        result['measured'].append(row)
        if limits:
            # One row per file, even if two limits are exceeded or the manifest repeats it.
            existing=next((r for r in result['over_limit'] if r['source']==row['source']),None)
            if existing:
                existing['size'].update(row['size'])
                for violation in limits:
                    if violation not in existing['limits']:existing['limits'].append(violation)
            else:result['over_limit'].append(row)
        if kind=='agent' and loaded!='listed':
            for role in item.get('role_paths',[]):
                role_path=Path(role).expanduser()
                if not role_path.is_absolute():role_path=path.parent/role_path
                queue.append(dict(path=str(role_path),kind='role',loaded='full'))
    if tool=='codex':
        chain=manifest.get('chain',[]);chain_stats=[]
        for named in chain:
            resolved=str(Path(named).expanduser().resolve())
            if resolved not in loaded_sizes:
                raise ValueError('chain member is not an attested loaded file: '+str(named))
            if resolved not in [p for p,_ in chain_stats]:chain_stats.append((resolved,loaded_sizes[resolved]))
        total={unit:sum(stats[unit] for _,stats in chain_stats) for unit in ('lines','words','bytes')}
        if total['bytes']>32768:
            result['over_limit'].append(dict(path='AGENTS.md chain',source='AGENTS.md chain',members=chain,
                size=total,limits=[dict(unit='bytes',measured=total['bytes'],limit=32768)],
                action='choose one chain member; run /slim-harness on that file'))
        if manifest.get('shortened_descriptions'):
            window=manifest.get('context_window')
            result['listing']=dict(budget=int(window*.02) if window else 8000,
                largest=sorted(descriptions,key=lambda d:d['characters'],reverse=True),trigger=False)
    return result


def markdown_table_cells(line):
    """Split unescaped pipes, allowing one optional outer delimiter per side."""
    line=line.strip(); cells=[]; start=0; escaped=False; has_pipe=False
    for index,char in enumerate(line):
        if char=='|' and not escaped:
            cells.append(line[start:index].strip());start=index+1;has_pipe=True
        escaped=char=='\\' and not escaped
    cells.append(line[start:].strip())
    if line.startswith('|'):cells.pop(0)
    if start==len(line) and has_pipe:cells.pop()
    return cells,has_pipe


def instruction_sentences(text):
    """Extract prose with physical line coordinates; see references/duplicates.md."""
    lines=text.splitlines(); start=0
    if lines and lines[0].strip()=='---':
        end=next((i for i in range(1,len(lines)) if lines[i].strip()=='---'),None)
        if end is None:raise ValueError('unterminated instruction frontmatter')
        start=end+1
    blocks=[]; block=[]; fence=None; comment=False; table=False; delimiter_line=None
    for number,line in enumerate(lines[start:],start+1):
        stripped=line.strip()
        marker=re.match(r'^(`{3,}|~{3,})',stripped)
        if fence:
            if re.fullmatch(re.escape(fence[0])+'{'+str(len(fence))+',}',stripped):fence=None
            continue
        if marker:
            if block:blocks.append(block);block=[]
            fence=marker.group(1);table=False;continue
        if comment or '<!--' in stripped:
            comment='-->' not in stripped;table=False
            if block:blocks.append(block);block=[]
            continue
        if table:
            if number==delimiter_line:continue
            # A table can contain short rows without a pipe; a blank or new
            # Markdown block ends it. Fences/comments are handled above.
            boundary=r'^(#{1,6}\s|>|(?:[-+*]|[0-9]+[.)])\s|[-*_]{3,}$)'
            if stripped and not re.match(boundary,stripped):continue
            table=False
        if number<len(lines):
            header,has_pipe=markdown_table_cells(stripped)
            delimiter,_=markdown_table_cells(lines[number])
            if (has_pipe and len(header)==len(delimiter) and delimiter
                    and all(re.fullmatch(r':?-+:?',cell) for cell in delimiter)):
                if block:blocks.append(block);block=[]
                table=True;delimiter_line=number+1;continue
        if not stripped or re.match(r'^(#{1,6}\s|\||[-*_]{3,}$)',stripped):
            if block:blocks.append(block);block=[]
            continue
        listed=re.match(r'^(?:[-+*]|[0-9]+[.)])\s+',stripped)
        if listed:
            if block:blocks.append(block);block=[]
            stripped=stripped[listed.end():]
        block.append((number,stripped))
    if block:blocks.append(block)
    sentences=[]
    for block in blocks:
        joined=''; coordinates=[]
        for number,line in block:
            if joined:joined+=' ';coordinates.append(number)
            joined+=line;coordinates.extend([number]*len(line))
        for match in re.finditer(r'\S.*?(?:[.!?](?=\s|$)|$)',joined):
            prose=match.group().strip()
            normalized=unicodedata.normalize('NFKC',prose).casefold().replace('’',"'")
            tokens=re.findall(r"\w+(?:'\w+)?",normalized)
            if len(tokens)<2 or len(' '.join(tokens))<10:continue
            sentences.append(dict(start_line=coordinates[match.start()],end_line=coordinates[match.end()-1],
                                  text=prose,tokens=tokens))
    return sentences


def duplicates(manifest):
    """Read only manifest-attested loaded files; report candidates without edits."""
    measured=measure(manifest)
    sources={row['source']:row for row in measured['measured'] if 'lines' in row['size']}
    files=[]
    for source,row in sorted(sources.items()):
        sentences=instruction_sentences(Path(source).read_bytes().decode('utf-8'))
        for sentence in sentences:
            sentence.update(path=row['path'],source=source)
        files.append(sentences)
    result=dict(duplicates=[],unresolved=measured['unresolved'])
    polarity={'not','no','never','always','only',"cannot","can't","don't","without"}
    for index,left in enumerate(files):
        for right in files[index+1:]:
            for a in left:
                for b in right:
                    at=a['tokens'];bt=b['tokens']
                    exact=at==bt
                    if not exact:
                        if min(len(at),len(bt))<8:continue
                        if min(len(' '.join(at)),len(' '.join(bt)))<40:continue
                        if 2*min(len(at),len(bt))/(len(at)+len(bt))<0.90:continue
                        if [t for t in at if t in polarity]!=[t for t in bt if t in polarity]:continue
                    score=1.0 if exact else SequenceMatcher(None,at,bt,autojunk=False).ratio()
                    if score<0.90:continue
                    spans=[{k:v for k,v in sentence.items() if k!='tokens'} for sentence in (a,b)]
                    result['duplicates'].append(dict(type='duplicate-rule',match='exact' if exact else 'near',
                        similarity=round(score,4),spans=spans,
                        action='run /slim-harness on the file that does not own this rule; confirm ownership with the user'))
    return result


def skill_sections(text):
    """Partition the body at ATX headings outside fences, without overlapping sizes."""
    _,body=frontmatter(text)
    sections=[]; title='Preamble'; lines=[]; start=1; fence=None
    for number,line in enumerate(body.splitlines(keepends=True),1):
        marker=re.match(r'^ {0,3}(`{3,}|~{3,})',line)
        if marker:
            if fence is None:fence=marker.group(1)
            elif re.fullmatch(re.escape(fence[0])+'{'+str(len(fence))+r',}\s*',line.strip()):fence=None
        heading=re.match(r'^ {0,3}#{1,6}\s+(.+?)\s*#*\s*$',line) if fence is None else None
        if heading:
            if lines and ''.join(lines).strip():sections.append((title,start,''.join(lines)))
            title=heading.group(1);lines=[];start=number
        lines.append(line)
    if lines and ''.join(lines).strip():sections.append((title,start,''.join(lines)))
    return sections


def usage_markers(text):
    """Conservative lexical evidence: literal flags, paths and backticked commands."""
    markers=set(re.findall(r'(?<![\w-])--[a-zA-Z][\w-]*',text))
    markers.update(re.findall(r'(?<![\w./~-])(?:~?/|\.\.?/|[\w.-]+/)[\w./~{}<>-]+',text))
    for code in re.findall(r'(?<!`)`([^`\n]+)`(?!`)',text):
        if re.match(r'^[a-zA-Z][\w.-]*(?: +[\w./-]+)+$',code):markers.add(code)
    for fence in re.finditer(r'(?ms)^ {0,3}(`{3,}|~{3,})(?:bash|sh|shell|zsh|console)?[ \t]*\n(.*?)^ {0,3}\1[ \t]*$',text):
        for line in fence.group(2).splitlines():
            command=re.match(r'^\s*(?:\$ )?([a-zA-Z][\w.-]*)(?: +([a-zA-Z][\w-]*))?',line)
            if command:markers.add(command.group(1)+(' '+command.group(2) if command.group(2) else ''))
    return sorted(markers)


def usage_commands(name,arguments):
    """Normalize shell commands including Codex exec's literal JS cmd fields.

    Never evaluate JS or shell; dynamic expressions are deliberately unsupported.
    """
    if isinstance(arguments,dict):
        command=arguments.get('command',arguments.get('cmd'))
        return [command] if isinstance(command,str) else []
    if not isinstance(arguments,str):return []
    try:
        value=json.loads(arguments)
    except ValueError:value=None
    if isinstance(value,dict):return usage_commands(name,value)
    commands=[]
    for match in re.finditer(r'(?<![\w])(?:"cmd"|cmd|"command"|command)\s*:\s*("(?:[^"\\]|\\.)*")',arguments):
        commands.append(json.loads(match.group(1)))
    return commands


def usage_reads(name,arguments,commands):
    """Recognize complete Read calls and literal cat operands; no partial reads."""
    paths=[]
    if name.lower() in ('read','read_file') and isinstance(arguments,dict):
        if not any(k in arguments for k in ('offset','limit','start_line','end_line')):
            path=arguments.get('file_path',arguments.get('path'))
            if isinstance(path,str):paths.append(path)
    for command in commands:
        try:
            lexer=shlex.shlex(command,posix=True,punctuation_chars=';&|<>')
            lexer.whitespace_split=True;tokens=list(lexer)
        except ValueError:continue
        if any(token in ('|','|&','>','>>','<','<<') for token in tokens):continue
        groups=[];group=[]
        for token in tokens+[';']:
            if token in (';','&&','||','|','&'):
                groups.append(group);group=[]
            else:group.append(token)
        for group in groups:
            if not group or group[0]!='cat':continue
            operands=group[1:]
            if any(t.startswith('-') and t!='--' or t in ('<','>','>>','<<') for t in operands):continue
            paths.extend(t for t in operands if t!='--' and not any(c in t for c in '$*?'))
    return paths


def usage_transcript(path,tool):
    """Return ordered normalized calls and a stable session identity when present."""
    calls=[];by_id={};identity=None;position=0
    with path.open(encoding='utf-8') as handle:
        for number,line in enumerate(handle,1):
            if not line.strip():continue
            try:row=json.loads(line)
            except ValueError as error:raise ValueError(f'{path}:{number}: invalid transcript JSON') from error
            if not isinstance(row,dict):raise ValueError(f'{path}:{number}: expected a record object')
            if tool=='claude':
                identity=identity or row.get('sessionId')
                blocks=row.get('message',{}).get('content',[])
                if not isinstance(blocks,list):continue
            else:
                payload=row.get('payload',{})
                if row.get('type')=='session_meta':identity=payload.get('id') or payload.get('session_id') or identity
                blocks=[payload] if row.get('type')=='response_item' else []
            for block in blocks:
                if not isinstance(block,dict):continue
                kind=block.get('type');position+=1
                if kind in ('tool_use','function_call','custom_tool_call'):
                    args=block.get('arguments',block.get('input',{}));name=block.get('name','')
                    if kind=='function_call' and isinstance(args,str):
                        try:args=json.loads(args)
                        except ValueError:pass
                    call=dict(name=name,arguments=args,commands=usage_commands(name,args),complete=None,position=position,completed_at=None)
                    calls.append(call);by_id[block.get('call_id',block.get('id'))]=call
                elif kind in ('tool_result','function_call_output','custom_tool_call_output'):
                    call=by_id.get(block.get('tool_use_id',block.get('call_id')))
                    if call is None:continue
                    # Status is metadata, never text inside a file or command output.
                    metadata=[block]
                    if isinstance(block.get('output'),dict):metadata.append(block['output'])
                    failed=any(record.get('is_error') or record.get('isError') or record.get('truncated')
                        or record.get('exit_code') not in (None,0)
                        or record.get('status') in ('failed','error','cancelled','running','in_progress')
                        for record in metadata)
                    call['complete']=not failed;call['completed_at']=position
    return calls,identity or str(path.resolve())


def usage(manifest):
    """Aggregate literal section evidence from explicit transcripts and skill snapshots."""
    rows={};seen=set();unresolved=[]
    for session in manifest.get('sessions',[]):
        tool=session['tool']
        if tool not in ('claude','codex'):raise ValueError('tool must be claude or codex')
        transcript=Path(session['transcript']).expanduser()
        calls,identity=usage_transcript(transcript,tool)
        # Repeated exports or paths of the same session never inflate the minimum.
        for skill in session.get('skills',[]):
            path=Path(skill['path']).expanduser();source=str(path.resolve())
            recorded=skill.get('recorded_path',str(path))
            key=(tool,identity,source)
            if key in seen:continue
            loaded_at=next((i for i,c in enumerate(calls) if c['complete'] is True
                and recorded in usage_reads(c['name'],c['arguments'],c['commands'])),None)
            if loaded_at is None:continue
            seen.add(key)
            if not path.is_file():
                unresolved.append(str(path));continue
            text=path.read_bytes().decode('utf-8')
            # Look only at subsequent tool inputs, never outputs, reasoning, or listings.
            evidence=[]
            for call in calls[loaded_at+1:]:
                if call['position']<=calls[loaded_at]['completed_at']:continue
                # Skill reads themselves do not prove use of instructions in that skill.
                if recorded in usage_reads(call['name'],call['arguments'],call['commands']):continue
                args=call['arguments']
                evidence.append(json.dumps(args,ensure_ascii=False) if isinstance(args,dict) else str(args))
            for title,start,body in skill_sections(text):
                rowkey=(source,start)
                if rowkey not in rows:
                    rows[rowkey]=dict(path=str(path),section=title,body_start_line=start,size=size(body),
                        sessions_loaded=0,sessions_with_evidence=0,markers=usage_markers(body),matched_markers=[])
                row=rows[rowkey];row['sessions_loaded']+=1
                matched=[marker for marker in row['markers'] if any(re.search(
                    r'(?<![\w./-])'+re.escape(marker)+r'(?![\w./-])',value) for value in evidence)]
                if matched:row['sessions_with_evidence']+=1
                row['matched_markers']=sorted(set(row['matched_markers']+matched))
    sections=[];candidates=[]
    for row in rows.values():
        row['status']='evidence of use' if row['sessions_with_evidence'] else 'no evidence of use'
        sections.append(row)
        if row['markers'] and row['sessions_loaded']>=3 and row['sessions_with_evidence']<row['sessions_loaded']:
            candidates.append(dict(path=row['path'],section=row['section'],body_start_line=row['body_start_line'],
                sessions_loaded=row['sessions_loaded'],reason='evidence in fewer sessions than loaded (at least 3); review for a possible split'))
    return dict(sections=sections,split_candidates=candidates,unresolved=sorted(set(unresolved)),
                minimum_sessions=3)


def dirty_repositories(paths):
    repos=set()
    for path in paths:
        root=subprocess.run(['git','-C',str(Path(path).parent),'rev-parse','--show-toplevel'],capture_output=True,text=True)
        if root.returncode==0:
            repo=root.stdout.strip()
            status=subprocess.run(['git','-C',repo,'status','--porcelain'],capture_output=True,text=True,check=True)
            if status.stdout:repos.add(repo)
    return sorted(repos)


def edit(path,before,after,journal,mode='interactive'):
    if mode!='interactive':
        return dict(changed=False,needs_user=True,message='slim-harness needs the user present; edited nothing')
    source=Path(path).expanduser().resolve(strict=True);current=source.read_bytes().decode('utf-8')
    if before==after:
        return dict(changed=False,source=str(source),dirty_repositories=[])
    if not before or not after:
        raise ValueError('include unchanged context around insertions and deletions')
    if current.count(before)!=1:
        raise ValueError('own lines are missing or ambiguous; use unique unchanged context')
    updated=current.replace(before,after,1)
    if updated.count(after)!=1:
        raise ValueError('result would be ambiguous to revert; include more unchanged context')
    journal=Path(journal)
    records=json.loads(journal.read_text()) if journal.exists() else []
    record=dict(number=len(records)+1,source=str(source),before=before,after=after,reverted=False)
    # Persist recovery information before changing the source; no full-file rollback.
    journal.write_text(json.dumps(records+[record],indent=2)+'\n')
    source.write_bytes(updated.encode('utf-8'))
    return dict(changed=True,source=str(source),number=record['number'],dirty_repositories=dirty_repositories([source]))


def revert(journal,number):
    journal=Path(journal);records=json.loads(journal.read_text());record=next(r for r in records if r['number']==number)
    source=Path(record['source']);current=source.read_bytes().decode('utf-8')
    if record['reverted']:
        return dict(changed=False,dirty_repositories=dirty_repositories([source]))
    if current.count(record['after'])!=1:
        raise ValueError('own lines changed or ambiguous; ask user to reconcile, never restore whole file')
    source.write_bytes(current.replace(record['after'],record['before'],1).encode('utf-8'));record['reverted']=True
    journal.write_text(json.dumps(records,indent=2)+'\n')
    return dict(changed=True,dirty_repositories=dirty_repositories([r['source'] for r in records]))


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    sub=parser.add_subparsers(dest='operation',required=True)
    p=sub.add_parser('measure');p.add_argument('manifest',type=Path)
    p=sub.add_parser('duplicates');p.add_argument('manifest',type=Path)
    p=sub.add_parser('usage');p.add_argument('manifest',type=Path)
    p=sub.add_parser('edit');p.add_argument('request',type=Path);p.add_argument('journal',type=Path)
    p=sub.add_parser('revert');p.add_argument('journal',type=Path);p.add_argument('number',type=int)
    args=parser.parse_args()
    try:
        if args.operation=='measure':result=measure(json.loads(args.manifest.read_text()))
        elif args.operation=='duplicates':result=duplicates(json.loads(args.manifest.read_text()))
        elif args.operation=='usage':result=usage(json.loads(args.manifest.read_text()))
        elif args.operation=='edit':result=edit(journal=args.journal,**json.loads(args.request.read_text()))
        else:result=revert(args.journal,args.number)
        print(json.dumps(result,indent=2));return 0
    except (OSError,ValueError,KeyError,StopIteration) as error:
        print(str(error),file=sys.stderr);return 2

if __name__=='__main__':
    sys.exit(main())
