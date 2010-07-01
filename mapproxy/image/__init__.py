# This file is part of the MapProxy project.
# Copyright (C) 2010 Omniscale <http://omniscale.de>
# 
# This program is free software: you can redistribute it and/or modify
# it under the terms of the GNU Affero General Public License as published by
# the Free Software Foundation, either version 3 of the License, or
# (at your option) any later version.
# 
# This program is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU Affero General Public License for more details.
# 
# You should have received a copy of the GNU Affero General Public License
# along with this program.  If not, see <http://www.gnu.org/licenses/>.

"""
Image and tile manipulation (transforming, merging, etc).
"""
from __future__ import with_statement
from cStringIO import StringIO

import Image
import ImageColor

from mapproxy.config import base_config

import logging
log = logging.getLogger(__name__)


class LayerMerger(object):
    """
    Merge multiple layers into one image.
    """
    def __init__(self):
        self.layers = []
    def add(self, layer):
        """
        Add one or more layers to merge. Bottom-layers first.
        """
        try:
            layer = iter(layer)
        except TypeError:
            if layer is not None:
                self.layers.append(layer)
        else:
            for l in layer:
                self.add(l)

    def merge(self, format='png', size=None, bgcolor='#ffffff', transparent=False):
        """
        Merge the layers. If the format is not 'png' just return the last image.
        
        :param format: The image format for the result.
        :param size: The size for the merged output.
        :rtype: `ImageSource`
        """
        if len(self.layers) == 1:
            if (self.layers[0].transparent == transparent):
                return self.layers[0]
        
        # TODO optimizations
        #  - layer with non transparency
        #         if not format.endswith('png'): #TODO png8?
        #             return self.layers[-1]
        
        if size is None:
            size = self.layers[0].size
        bgcolor = ImageColor.getrgb(bgcolor)
        if transparent:
            img = Image.new('RGBA', size, bgcolor+(0,))
        else:
            img = Image.new('RGB', size, bgcolor)
        for layer in self.layers:
            layer_img = layer.as_image()
            if layer_img.mode == 'RGBA':
                # paste w transparency mask from layer
                img.paste(layer_img, (0, 0), layer_img)
            else:
                img.paste(layer_img, (0, 0))
        return ImageSource(img, format)

def merge_images(images, format='png', size=None, transparent=True):
    """
    Merge multiple images into one.
    
    :param images: list of `ImageSource`, bottom image first
    :param format: the format of the output `ImageSource`
    :param size: size of the merged image, if ``None`` the size
                 of the first image is used
    :rtype: `ImageSource`
    """
    merger = LayerMerger()
    merger.add(images)
    return merger.merge(format=format, size=size, transparent=transparent)

class ImageSource(object):
    """
    This class wraps either a PIL image, a file-like object, or a file name.
    You can access the result as an image (`as_image` ) or a file-like buffer
    object (`as_buffer`).
    """
    def __init__(self, source, format='png', size=None, transparent=False):
        """
        :param source: the image
        :type source: PIL `Image`, image file object, or filename
        :param format: the format of the ``source``
        :param size: the size of the ``source`` in pixel
        """
        self._img = None
        self._buf = None
        self._fname = None
        self.source = source
        self.format = format
        self.transparent = transparent
        self._size = size
    
    def _set_source(self, source):
        self._img = None
        self._buf = None
        if isinstance(source, basestring):
            self._fname = source
        elif isinstance(source, Image.Image):
            self._img = source
        else:
            self._buf = source
    
    def _get_source(self):
        return self._img or self._buf or self._fname
    
    source = property(_get_source, _set_source)
    
    @property
    def filename(self):
        return self._fname
    
    def as_image(self):
        """
        Returns the image or the loaded image.
        
        :rtype: PIL `Image`
        """
        if self._img: return self._img
        
        self._make_seekable_buf()
        log.debug('file(%s) -> image', self._fname or self._buf)
        
        try:
            img = Image.open(self._buf)
        except StandardError:
            try:
                self._buf.close()
            except:
                pass
            raise
        self._img = img
        return img
    
    def _make_seekable_buf(self):
        if not self._buf and self._fname:
            self._buf = open(self._fname, 'rb')
        elif not hasattr(self._buf, 'seek'):
            # PIL needs file objects with seek
            self._buf = StringIO(self._buf.read())
        self._buf.seek(0)
    
    def _make_readable_buf(self):
        if not self._buf and self._fname:
            self._buf = open(self._fname, 'rb')
        elif not hasattr(self._buf, 'seek'):
            if isinstance(self._buf, ReadBufWrapper):
                self._buf = ReadBufWrapper(self._buf)
        else:
            self._buf.seek(0)
    
    def as_buffer(self, format=None, paletted=None, seekable=False):
        """
        Returns the image as a file object.
        
        :param format: The format to encode an image.
                       Existing files will not be re-encoded.
        :rtype: file-like object
        """
        if not self._buf and not self._fname:
            if not format:
                format = self.format
            log.debug('image -> buf(%s)' % (format,))
            self._buf = img_to_buf(self._img, format, paletted=paletted)
        else:
            self._make_seekable_buf() if seekable else self._make_readable_buf()
            if self.format and format and self.format != format:
                log.debug('converting image from %s -> %s' % (self.format, format))
                self.source = self.as_image()
                self._buf = None
                self.format = format
                # hide fname to prevent as_buffer from reading the file
                fname = self._fname
                self._fname = None
                self.as_buffer(format=format, paletted=paletted)        
                self._fname = fname
        return self._buf

    @property
    def size(self):
        if isinstance(self.source, Image.Image):
            return self.source.size
        else:
            return self._size

class ReadBufWrapper(object):
    """
    This class wraps everything with a ``read`` method and adds support
    for ``seek``, etc. A call to everything but ``read`` will create a
    StringIO object of the ``readbuf``.
    """
    def __init__(self, readbuf):
        self.ok_to_seek = False
        self.readbuf = readbuf
        self.stringio = None
    
    def read(self, *args, **kw):
        if self.stringio:
            return self.stringio.read(*args, **kw)
        return self.readbuf.read(*args, **kw)
    
    def __iter__(self):
        if self.stringio:
            return iter(self.stringio)
        else:
            return iter(self.readbuf)
    
    def __getattr__(self, name):
        if self.stringio is None:
            if hasattr(self.readbuf, name):
                return getattr(self.readbuf, name)
            elif name == '__length_hint__':
                raise AttributeError
            self.ok_to_seek = True
            self.stringio = StringIO(self.readbuf.read())
        return getattr(self.stringio, name)

def img_to_buf(img, format='png', paletted=None):
    defaults = {}
    if paletted is None:
        paletted = base_config().image.paletted
    if paletted:
        if format in ('png', 'gif'):
            if img.mode == 'RGBA':
                alpha = img.split()[3]
                img = quantize(img, colors=255)
                mask = Image.eval(alpha, lambda a: 255 if a <=128 else 0)
                img.paste(255, mask)
                defaults['transparency'] = 255
            else:
                img = quantize(img)
            if hasattr(Image, 'RLE'):
                defaults['compress_type'] = Image.RLE
    format = filter_format(format)
    buf = StringIO()
    if format == 'jpeg':
        defaults['quality'] = base_config().image.jpeg_quality
    img.save(buf, format, **defaults)
    buf.seek(0)
    return buf

def quantize(img, colors=256):
    if hasattr(Image, 'FASTOCTREE'):
        return img.quantize(colors, Image.FASTOCTREE)
    return img.convert('RGB').convert('P', palette=Image.ADAPTIVE, colors=colors)
    
def filter_format(format):
    if format.lower() == 'geotiff':
        format = 'tiff'
    if format.lower().startswith('png'):
        format = 'png'
    return format

image_filter = { 
    'nearest': Image.NEAREST,
    'bilinear': Image.BILINEAR,
    'bicubic': Image.BICUBIC
}


def is_single_color_image(image):
    """
    Checks if the `image` contains only one color.
    Returns ``False`` if it contains more than one color, else
    the color-tuple of the single color.
    """
    result = image.getcolors(1)
    # returns a list of (count, color), limit to one
    if result is None:
        return False
    
    color = result[0][1]
    if image.mode == 'P':
        palette = image.getpalette()
        return palette[color*3], palette[color*3+1], palette[color*3+2]
    
    return result[0][1]