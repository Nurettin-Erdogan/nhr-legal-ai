"""Kullanıcının seçtiği Drive dosyaları ve Word görev bölmesi. Google jetonları tutulmaz."""
from __future__ import annotations
import asyncio
import os
import re
from typing import Annotated
from urllib.parse import urlparse
from uuid import UUID
from xml.sax.saxutils import escape
from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import Response
from api.auth.routes import current_user_id
from api.audit import AuditContext

router=APIRouter(prefix='/api/integrations',tags=['integrations'])


def word_origin() -> str:
    origin=os.getenv('WORD_ADDIN_ORIGIN','').strip().rstrip('/')
    try:
        parsed=urlparse(origin)
        port=parsed.port
    except ValueError:
        return ''
    if (parsed.scheme!='https' or not parsed.hostname or parsed.username or parsed.password
            or parsed.path or parsed.query or parsed.fragment or re.search(r'[\s<>"\x27]',origin)
            or (port is not None and not 1<=port<=65535)):
        return ''
    return origin


@router.get('/config')
def integration_config():
    client=os.getenv('GOOGLE_DRIVE_CLIENT_ID',os.getenv('GOOGLE_CLIENT_ID','')).strip()
    key=os.getenv('GOOGLE_PICKER_API_KEY','').strip()
    project=os.getenv('GOOGLE_CLOUD_PROJECT_NUMBER','').strip()
    origin=word_origin()
    return {'drive':{'configured':bool(client and key and project),'client_id':client,'api_key':key,'project_number':project},
            'word':{'configured':bool(origin),'origin':origin,'manifest_path':'/api/integrations/word/manifest'}}


@router.post('/drive/import')
async def import_drive(request:Request,owner:Annotated[UUID,Depends(current_user_id)]):
    from api.office_public import read_document_upload, _store
    fields,name,mime,upload=await read_document_upload(request)
    if upload.size > 50 * 1024 * 1024:
        upload.discard()
        raise HTTPException(413,'Drive içe aktarımında dosya başına en fazla 50 MB destekleniyor.')
    result,document_id=await asyncio.to_thread(_store,owner,file_name=name,data=upload,source='google_drive',
        mime_type=mime,overrides={},dedupe_by_source=False,audit=AuditContext.from_request(request))
    if result not in ('inserted','duplicate') or document_id is None:
        raise HTTPException(503,'Drive belgesi kaydedilemedi.')
    return {'id':document_id,'duplicate':result=='duplicate'}


def word_manifest(origin:str) -> str:
    root=escape(origin)
    return f'''<?xml version="1.0" encoding="UTF-8"?>
<OfficeApp xmlns="http://schemas.microsoft.com/office/appforoffice/1.1" xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance" xsi:type="TaskPaneApp">
<Id>ed1f2d76-8405-4db6-8c9d-7d913d29586f</Id><Version>1.0.0.0</Version><ProviderName>NHR Yazılım</ProviderName><DefaultLocale>tr-TR</DefaultLocale>
<DisplayName DefaultValue="JurisAI"/><Description DefaultValue="Word belgenizi JurisAI ile inceleyin ve seçtiğiniz sonucu belgenize ekleyin."/>
<IconUrl DefaultValue="{root}/jurisai-avukat/images/icon-48.png"/>
<SupportUrl DefaultValue="{root}/sss"/><AppDomains><AppDomain>{root}</AppDomain></AppDomains>
<Hosts><Host Name="Document"/></Hosts><Requirements><Sets DefaultMinVersion="1.1"><Set Name="WordApi" MinVersion="1.1"/></Sets></Requirements>
<DefaultSettings><SourceLocation DefaultValue="{root}/word/taskpane.html"/></DefaultSettings><Permissions>ReadWriteDocument</Permissions>
</OfficeApp>'''


@router.get('/word/manifest')
def download_word_manifest():
    origin=word_origin()
    if not origin: raise HTTPException(503,'Word eklentisi için HTTPS WORD_ADDIN_ORIGIN ayarı gerekli.')
    return Response(word_manifest(origin),media_type='application/xml',headers={'Content-Disposition':'attachment; filename="jurisai-word.xml"'})
