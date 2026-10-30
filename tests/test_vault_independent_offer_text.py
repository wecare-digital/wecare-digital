"""Contract tests: UUID storage names must never become WhatsApp variable text."""
import ast
import os
import re
import uuid
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SERVICE = ROOT / "amplify/functions/core/service-api/handler.py"
FILES = ROOT / "amplify/functions/core/secure-files/handler.py"
CATALOG = ROOT / "amplify/functions/messaging/whatsapp-business-api/flows/catalog_services.py"
WORKSPACE = ROOT / "src/components/workspace/service/SecureFiles.tsx"
PREVIEW = ROOT / "src/components/workspace/service/VaultJourneyPreview.tsx"
CLIENT = ROOT / "src/api/client.ts"


def source(path):
    return path.read_text(encoding="utf-8")


def test_uploaded_file_basename_is_wecare_digital_uuid_not_original():
    program = ast.parse(source(SERVICE))
    functions = [
        n for n in program.body
        if isinstance(n, ast.FunctionDef)
        and n.name in {"_extension_for_upload", "_generated_document_name"}
    ]
    assert len(functions) == 2
    sandbox = {"os": os, "re": re, "uuid": uuid}
    exec(compile(ast.Module(body=functions, type_ignores=[]), str(SERVICE), "exec"), sandbox)
    name = sandbox["_generated_document_name"]("private-filename.pdf", "application/pdf")
    assert re.fullmatch(r"wecare-digital-[0-9a-f]{32}\.pdf", name)
    assert "private-filename" not in name
    other = sandbox["_generated_document_name"]("private-filename.pdf", "application/pdf")
    assert other != name


def test_uuid_name_is_s3_basename_and_download_name():
    service = source(SERVICE)
    secure = source(FILES)
    assert "storage_key = media_paths.DROP_DOCS_UPLOAD_PREFIX + 'manual/' + generated_name" in service
    assert "replacement_key = media_paths.DROP_DOCS_UPLOAD_PREFIX + 'manual/' + generated_name" in service
    assert "item['originalFileName'] = generated_name" in service
    assert "':original': generated_name" in service
    assert "new_name = str(current.get('fileName') or current.get('originalFileName') or '')" in service
    assert '"displayName": display_name' in secure
    assert 'f\'attachment; filename="{_system_name_for_file(item)}"\'' in secure
    assert "_vault_system_name(document, file_id)" in secure


def test_free_text_body_parameter_is_independent_of_file_name():
    api = source(CLIENT)
    front = source(WORKSPACE)
    preview = source(PREVIEW)
    secure = source(FILES)
    catalog = source(CATALOG)
    assert 'maxLength={ 60 }' in front
    assert 'offerBodyText={ offerBodyText }' in front
    assert 'api.sendSecureFileOffer( target.fileId, variable )' in front
    assert 'api.sendSecureFileOffer( published.data.fileId, variable! )' not in front
    upload = front.split('const handleUpload = async () => {', 1)[1].split('const handleRevoke', 1)[0]
    assert 'sendSecureFileOffer' not in upload
    assert 'Save document to Vault' in front
    assert 'JSON.stringify( { offerBodyText: options.offerBodyText } )' in api
    assert 'send_payload["offerBodyText"] = offer_text' in secure
    assert 'whatsapp_templates.vault_offer_document_name(candidate) != candidate' in secure
    assert "offer_body_text, token" in catalog
    assert "'offerBodyText': offer_body_text" in catalog
    assert 'stageBody( activeStage, offerBodyText )' in preview
    assert 'stageBody( activeStage, fileName )' not in preview


def test_offer_action_stays_bound_to_published_file_and_signed_customer():
    secure = source(FILES)
    catalog = source(CATALOG)
    assert '_owned_file_for_admin(file_id)' in secure
    assert '"fileId": str(item["fileId"])' in secure
    assert '"ownerCustomerId": str(item["ownerCustomerId"])' in secure
    assert "'status': 'SENDING'" in catalog
    assert "'VAULT_OFFER_TEXT_INVALID'" in catalog
    assert "idempotencyKey='vault-offer:' + token" in catalog
