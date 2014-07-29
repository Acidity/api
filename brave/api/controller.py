# encoding: utf-8

from __future__ import unicode_literals

from datetime import datetime
from binascii import hexlify, unhexlify
from hashlib import sha256
from ecdsa.keys import SigningKey, VerifyingKey
from ecdsa.curves import NIST256p

from webob import Response
from web.core.http import HTTPBadRequest
from web.core import request, Controller
from web.core.templating import render


log = __import__('logging').getLogger(__name__)


class SignedController(Controller):
    def __service__(self, value):
        raise NotImplementedError()
    
    def __before__(self, *args, **kw):
        """Validate the request signature, load the relevant data."""
        
        if 'X-Service' not in request.headers:
            log.error("Digitally signed request missing headers.")
            raise HTTPBadRequest("Missing headers.")
        
        try:
            request.service = self.__service__(request.headers['X-Service'])
        except:
            log.exception("Exception attempting to load service: %s", request.headers['X-Service'])
            raise HTTPBadRequest("Unknown or invalid service identity.")
        
        if request.service.exempt_encryption:
            log.debug("Request exempt from encryption, skipping validation")
            # Check that the remote IP Address matches the one we have for this application
            # Try to maintain some kind of security...
            if request.service.exempt_address and request.remote_addr != request.service.exempt_address:
                log.info("Received incorrect request from IP: {0}".format(request.remote_addr))
                raise HTTPBadRequest("Incorrect IP Address.")
            log.debug("Canonical request:\n\n\"{r.headers[Date]}\n{r.url}\n{r.body}\"".format(r=request))
            return args, kw
        
        if 'X-Signature' not in request.headers:
            log.error("Digitally signed request missing headers.")
            raise HTTPBadRequest("Missing headers.")
        
        hex_key = request.service.key.public.encode('utf-8')
        key = VerifyingKey.from_string(unhexlify(hex_key), curve=NIST256p, hashfunc=sha256)
        
        log.debug("Canonical request:\n\n\"{r.headers[Date]}\n{r.url}\n{r.body}\"".format(r=request))
        
        if not key.verify(
                unhexlify(request.headers['X-Signature']),
                "{r.headers[Date]}\n{r.url}\n{r.body}".format(r=request)):
            raise HTTPBadRequest("Invalid request signature.")
        
        return args, kw
    
    def __after__(self, result, *args, **kw):
        """Generate the JSON response and sign."""
        
        response = Response(status=200, charset='utf-8')
        response.date = datetime.utcnow()
        response.last_modified = result.pop('updated', None)
        
        ct, body = render('json:', result)
        response.headers[b'Content-Type'] = str(ct)  # protect against lack of conversion in Flup
        response.body = body
        
        canon = "{req.service.id}\n{resp.headers[Date]}\n{req.url}\n{resp.body}".format(
                    req = request,
                    resp = response
            )
            
        if request.service.exempt_encryption:
            log.debug("Canonical data:\n%r", canon)
        
            del response.date  # TODO: This works around an odd bug of sending two Date header values.
        
            return response
        
        key = SigningKey.from_string(unhexlify(request.service.key.private), curve=NIST256p, hashfunc=sha256)
        response.headers[b'X-Signature'] = hexlify(key.sign(canon))
        log.debug("Signing response: %s", response.headers[b'X-Signature'])
        
        log.debug("Canonical data:\n%r", canon)
        
        del response.date  # TODO: This works around an odd bug of sending two Date header values.
        
        return response
