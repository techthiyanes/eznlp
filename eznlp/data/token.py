# -*- coding: utf-8 -*-
from typing import List
from collections import OrderedDict
from functools import cached_property
import string
import re
import hanziconv
import spacy
import jieba
import numpy as np


zh_punctuation = "！？｡。＂＃＄％＆＇（）＊＋，－——／：；＜＝＞＠［＼］＾＿｀｛｜｝～｟｠｢｣､、〃《》「」『』【】〔〕〖〗〘〙〚〛〜〝〞〟〰〾〿–—‘’‛“”„‟…‧﹏"

ascii_re = re.compile('[\x00-\xff]')
lower_re = re.compile('[a-z]')
upper_re = re.compile('[A-Z]')
digit_re = re.compile('\d')
punct_re = re.compile('[' + ''.join("\\" + p for p in string.punctuation) + ']')
non_ascii_re = re.compile('[^\x00-\xff]')
zh_punct_re = re.compile('[' + zh_punctuation + ']')

en_title_word_re = re.compile('[A-Z]{1}[a-z]{1,}')
en_upper_word_re = re.compile('[A-Z]{2,}')
en_lower_word_re = re.compile('[a-z]{2,}')

en_shape2criterion = [('any_ascii', lambda x: ascii_re.search(x) is not None), 
                      ('any_non_ascii', lambda x: non_ascii_re.search(x) is not None), 
                      ('any_upper', lambda x: upper_re.search(x) is not None), 
                      ('any_lower', lambda x: lower_re.search(x) is not None), 
                      ('any_digit', lambda x: digit_re.search(x) is not None), 
                      ('any_punct', lambda x: punct_re.search(x) is not None), 
                      ('init_upper', lambda x: upper_re.search(x[0]) is not None), 
                      ('init_lower', lambda x: lower_re.search(x[0]) is not None), 
                      ('init_digit', lambda x: digit_re.search(x[0]) is not None), 
                      ('init_punct', lambda x: punct_re.search(x[0]) is not None), 
                      ('any_noninit_upper', lambda x: upper_re.search(x[1:]) is not None), 
                      ('any_noninit_lower', lambda x: lower_re.search(x[1:]) is not None), 
                      ('any_noninit_digit', lambda x: digit_re.search(x[1:]) is not None), 
                      ('any_noninit_punct', lambda x: punct_re.search(x[1:]) is not None), 
                      ('typical_title', lambda x: en_title_word_re.fullmatch(x) is not None), 
                      ('typical_upper', lambda x: en_upper_word_re.fullmatch(x) is not None), 
                      ('typical_lower', lambda x: en_lower_word_re.fullmatch(x) is not None), 
                      ('apostrophe_end', lambda x: x[-1] == "'" or x[-2:].lower() == "'s")]
en_shape2criterion = OrderedDict(en_shape2criterion)

stopwords = {"a", "about", "above", "after", "again", "against", "all", "am", 
             "an", "and", "any", "are", "aren't", "as", "at", "be", "because", 
             "been", "before", "being", "below", "between", "both", "but", 
             "by", "can't", "cannot", "could", "couldn't", "did", "didn't", 
             "do", "does", "doesn't", "doing", "don't", "down", "during", 
             "each", "few", "for", "from", "further", "had", "hadn't", "has", 
             "hasn't", "have", "haven't", "having", "he", "he'd", "he'll", 
             "he's", "her", "here", "here's", "hers", "herself", "him", 
             "himself", "his", "how", "how's", "i", "i'd", "i'll", "i'm", 
             "i've", "if", "in", "into", "is", "isn't", "it", "it's", "its", 
             "itself", "let's", "me", "more", "most", "mustn't", "my", 
             "myself", "no", "nor", "not", "of", "off", "on", "once", "only", 
             "or", "other", "ought", "our", "ours", "ourselves", "out", "over", 
             "own", "same", "shan't", "she", "she'd", "she'll", "she's", 
             "should", "shouldn't", "so", "some", "such", "than", "that", 
             "that's", "the", "their", "theirs", "them", "themselves", "then", 
             "there", "there's", "these", "they", "they'd", "they'll", 
             "they're", "they've", "this", "those", "through", "to", "too", 
             "under", "until", "up", "very", "was", "wasn't", "we", "we'd", 
             "we'll", "we're", "we've", "were", "weren't", "what", "what's", 
             "when", "when's", "where", "where's", "which", "while", "who", 
             "who's", "whom", "why", "why's", "with", "won't", "would", 
             "wouldn't", "you", "you'd", "you'll", "you're", "you've", "your", 
             "yours", "yourself", "yourselves"}


class Full2Half(object):
    '''Translate full-width characters to half-widths
    '''
    _f2h = {fc: hc for fc, hc in zip(range(0xFF01, 0xFF5E), range(0x21, 0x7E))}
    _f2h.update({0x3000: 0x20})
    _h2f = {hc: fc for fc, hc in _f2h.items()}
    
    @staticmethod
    def full2half(text):
        return text.translate(Full2Half._f2h)
    
    @staticmethod
    def half2full(text):
        return text.translate(Full2Half._h2f)
    
    
SHORT_LEN = 3
MAX_DIGITS = 4

def _adaptive_lower(text):
    if len(text) <= 1 or text.islower():
        return text
    
    lowered = text.lower()
    if lowered in stopwords:
        return lowered
    
    if len(text) > SHORT_LEN and en_title_word_re.fullmatch(text):
        return lowered
    
    if len(text) > (SHORT_LEN+2) and en_upper_word_re.fullmatch(text):
        return lowered
    
    return text


class Token(object):
    """
    A token at the modeling level (e.g., word level for English text, or character level for Chinese text). 
    
    `Token` provides access to lower-level attributes (prefixes, suffixes). 
    """
    _num_feature_names = [f"<{num_type}{digits}>" for num_type in ['int', 'real', 'percent'] for digits in range(MAX_DIGITS+1)] \
                       + [f"<-{num_type}{digits}>" for num_type in ['int', 'real', 'percent'] for digits in range(MAX_DIGITS+1)]
    _en_shape_feature_names = list(en_shape2criterion.keys())
    
    _basic_enum_fields = ['prefix_2', 'prefix_3', 'prefix_4', 'prefix_5', 
                          'suffix_2', 'suffix_3', 'suffix_4', 'suffix_5', 
                          'en_pattern', 'en_pattern_sum']
    _basic_val_fields = ['en_shape_features', 'num_features']
    
    def __init__(self, raw_text, case_mode='None', number_mode='None', to_half=True, to_zh_simplified=False, **kwargs):
        self.raw_text = raw_text
        if case_mode.lower() == 'none':
            self.text = raw_text
        elif case_mode.lower() == 'lower':
            self.text = raw_text.lower()
        elif case_mode.lower() == 'adaptive-lower':
            self.text = _adaptive_lower(raw_text)
        else:
            raise ValueError(f"Invalid value of case_mode: {case_mode}")
            
        if number_mode.lower() == 'none':
            pass
        elif number_mode.lower() == 'marks':
            self.text = self.num_mark
        elif number_mode.lower() == 'zeros':
            self.text = digit_re.sub('0', self.text)
        else:
            raise ValueError(f"Invalid value of num_mode: {number_mode}")
            
        self.text = Full2Half.full2half(self.text) if to_half else self.text
        self.text = hanziconv.HanziConv.toSimplified(self.text) if to_zh_simplified else self.text
        for k, v in kwargs.items():
            setattr(self, k, v)
            
            
    def __len__(self):
        return len(self.raw_text)
    
    def __repr__(self):
        return self.raw_text
    
    @property    
    def prefix_2(self):
        return self.raw_text[:2]
    
    @property
    def prefix_3(self):
        return self.raw_text[:3]
    
    @property
    def prefix_4(self):
        return self.raw_text[:4]
    
    @property
    def prefix_5(self):
        return self.raw_text[:5]
    
    @property
    def suffix_2(self):
        return self.raw_text[-2:]
    
    @property
    def suffix_3(self):
        return self.raw_text[-3:]
    
    @property
    def suffix_4(self):
        return self.raw_text[-4:]
    
    @property
    def suffix_5(self):
        return self.raw_text[-5:]
    
    @property
    def num_features(self):
        features = np.zeros((MAX_DIGITS + 1) * 6, dtype=bool)
        
        if self.raw_text.endswith('%'):
            text4num = self.raw_text[:-1]
            is_percent = True
        else:
            text4num = self.raw_text
            is_percent = False
            
        try:
            possible_value = float(text4num)
        except:
            return features
        else:
            if abs(possible_value) < 1:
                offset = 0
            else:
                offset = min(MAX_DIGITS, int(np.log10(abs(possible_value))) + 1)
                
            if is_percent:
                offset += (MAX_DIGITS + 1) * 2
            elif '.' in text4num:
                offset += (MAX_DIGITS + 1)
                
            if possible_value < 0:
                offset += (MAX_DIGITS + 1) * 3
                
            features[offset] = True
            return features
        
        
    @property
    def num_mark(self):
        num_features = self.num_features
        if not num_features.any():
            return self.text
        else:
            return self._num_feature_names[num_features.tolist().index(True)]
        
    @property
    def en_pattern(self):
        feature = upper_re.sub('A', self.raw_text)
        feature = lower_re.sub('a', feature)
        feature = digit_re.sub('0', feature)
        return feature
    
    @property
    def en_pattern_sum(self):
        feature = self.en_pattern
        feature = re.sub('A+', 'A', feature)
        feature = re.sub('a+', 'a', feature)
        feature = re.sub('0+', '0', feature)
        return feature
        
    @property
    def en_shape_features(self):
        return np.array([criterion(self.raw_text) for criterion in en_shape2criterion.values()])
        
    @property
    def zh_shape_features(self):
        return None
    
    
    
class TokenSequence(object):
    """
    A wrapper of token list, providing sequential attribute access to all tokens. 
    """
    _softword_idx2tag = ['B', 'M', 'E', 'S']
    _softword_tag2idx = {t: i for i, t in enumerate(_softword_idx2tag)}
    
    def __init__(self, token_list: List[Token], token_sep=" ", pad_token="<pad>"):
        self.token_list = token_list
        self.token_sep = token_sep
        self.pad_token = pad_token
        
    def __getattr__(self, name):
        # NOTE: `__attr__` method is only invoked if the attribute wasn't found the usual ways, so 
        # it is good for implementing a fallback for missing attributes. While, `__getattribute__`
        # is invoked before looking at the actual attributes on the object. 
        # See: https://stackoverflow.com/questions/3278077/difference-between-getattr-vs-getattribute
        if hasattr(self.token_list[0], name):
            return [getattr(tok, name) for tok in self.token_list]
        else:
            raise AttributeError(f"type object {self.__class__.__name__} has no attribute {name}")
            
    def __len__(self):
        return len(self.token_list)
    
    def __repr__(self):
        return repr(self.token_list)
    
    def __getstate__(self):
        return {'token_list': self.token_list, 
                'token_sep': self.token_sep, 
                'pad_token': self.pad_token}
        
    def __setstate__(self, state: dict):
        for name, value in state.items():
            setattr(self, name, value)
            
            
    def __getitem__(self, i):
        if isinstance(i, int):
            return self.token_list[i]
        elif isinstance(i, slice):
            return TokenSequence(self.token_list[i], token_sep=self.token_sep, pad_token=self.pad_token)
        else:
            raise TypeError(f"Invalid subscript type of {i}")
            
    def __add__(self, other):
        return TokenSequence(self.token_list + other.token_list, token_sep=self.token_sep, pad_token=self.pad_token)
    
    
    def build_pseudo_boundaries(self, sep_width: int=None):
        if sep_width is None:
            sep_width = len(self.token_sep)
        
        token_lens = np.array([len(tok) for tok in self.token_list])
        self.end = np.cumsum(token_lens + sep_width) - sep_width
        self.start = self.end - token_lens
        
        
    def build_softwords(self, tokenize_callback):
        self.softword = [np.zeros(len(self._softword_idx2tag), dtype=bool) for tok in self.token_list]
        
        if hasattr(tokenize_callback, '__self__') and isinstance(tokenize_callback.__self__, jieba.Tokenizer) and tokenize_callback.__name__.startswith('tokenize'):
            pass
        else:
            raise ValueError(f"Invalid `tokenize_callback`: {tokenize_callback}")
            
        for word_text, word_start, word_end in tokenize_callback("".join(self.raw_text)):
            if word_end - word_start == 1:
                self.softword[word_start][self._softword_tag2idx['S']] = True
            else:
                self.softword[word_start][self._softword_tag2idx['B']] = True
                self.softword[word_end-1][self._softword_tag2idx['E']] = True
                for k in range(word_start+1, word_end-1):
                    self.softword[k][self._softword_tag2idx['M']] = True
                    
                    
    @cached_property
    def bigram(self):
        unigram = self.text
        return [self.token_sep.join(gram) for gram in zip(unigram, unigram[1:]+[self.pad_token])]
    
    @cached_property
    def trigram(self):
        unigram = self.text
        return [self.token_sep.join(gram) for gram in zip(unigram, unigram[1:]+[self.pad_token], unigram[2:]+[self.pad_token, self.pad_token])]
        
    
    def spans_within_max_length(self, max_len: int):
        total_len = len(self.token_list)
        slice_start = 0
        
        while True:
            if total_len - slice_start <= max_len:
                yield slice(slice_start, total_len)
                break
            else:
                slice_end = slice_start + max_len
                while not self.token_list[slice_end-1].text in ('.', '?', '!', ';'):
                    slice_end -= 1
                    if slice_end <= slice_start:
                        raise ValueError(f"Cannot find proper slices in {self.token_list[slice_start:slice_start+max_len]}")
                yield slice(slice_start, slice_end)
                slice_start = slice_end
                
                
    def attach_additional_tags(self, additional_tags: dict=None, additional_tok2tags: list=None):
        """
        Parameters
        ----------
        additional_tags : dict of lists, optional
            {tag_name: tags, ...}. 
        additional_tok2tags : list of tuples, optional
            [(tag_name: str, tok2tag: dict), ...]. 
        """
        if additional_tags is not None:
            for tag_name, tags in additional_tags.items():
                for tok, tag in zip(self.token_list, tags):
                    setattr(tok, tag_name, tag)
                    
        if additional_tok2tags is not None:
            for tag_name, tok2tag in additional_tok2tags:
                for tok in self.token_list:
                    setattr(tok, tag_name, tok2tag.get(tok.text, tok2tag['<unk>']))
                    
        return self
    
    
    @classmethod
    def from_tokenized_text(cls, tokenized_text: list, additional_tags=None, additional_tok2tags=None, 
                            token_sep=" ", pad_token="<pad>", **kwargs):
        token_list = [Token(tok_text, **kwargs) for tok_text in tokenized_text]
        tokens = cls(token_list, token_sep=token_sep, pad_token=pad_token)
        tokens.attach_additional_tags(additional_tags=additional_tags, additional_tok2tags=additional_tok2tags)
        return tokens
    
    
    @classmethod
    def from_raw_text(cls, raw_text: str, tokenize_callback=None, additional_tok2tags=None, 
                      token_sep=" ", pad_token="<pad>", **kwargs):
        if tokenize_callback is None:
            token_list = [Token(tok_text, **kwargs) for tok_text in raw_text.split()]
        elif isinstance(tokenize_callback, spacy.language.Language):
            token_list = [Token(tok.text, start=tok.idx, end=tok.idx+len(tok.text), **kwargs) for tok in tokenize_callback(raw_text)]
        elif hasattr(tokenize_callback, '__self__') and isinstance(tokenize_callback.__self__, jieba.Tokenizer):
            if tokenize_callback.__name__.startswith('tokenize'):
                token_list = [Token(tok_text, start=tok_start, end=tok_end, **kwargs) for tok_text, tok_start, tok_end in tokenize_callback(raw_text)]
            elif tokenize_callback.__name__.startswith('cut'):
                token_list = [Token(tok_text, **kwargs) for tok_text in tokenize_callback(raw_text)]
            else:
                raise ValueError(f"Invalid method of `jieba.Tokenizer`: {tokenize_callback}")
        else:
            raise ValueError(f"Invalid `tokenize_callback`: {tokenize_callback}")
        
        tokens = cls(token_list, token_sep=token_sep, pad_token=pad_token)
        tokens.attach_additional_tags(additional_tok2tags=additional_tok2tags)
        return tokens
    
    
    
def custom_spacy_tokenizer(nlp, custom_prefixes=None, custom_suffixes=None, custom_infixes=None):
    """
    References:
    https://spacy.io/usage/linguistic-features#tokenization
    http://www.longest.io/2018/01/27/spacy-custom-tokenization.html
    """
    if custom_prefixes is None:
        prefix_search = nlp.tokenizer.prefix_search
    else:
        prefix_search = spacy.util.compile_prefix_regex(tuple(list(nlp.Defaults.prefixes) + custom_prefixes)).search
    if custom_suffixes is None:
        suffix_search = nlp.tokenizer.suffix_search
    else:
        suffix_search = spacy.util.compile_suffix_regex(tuple(list(nlp.Defaults.suffixes) + custom_suffixes)).search
    if custom_infixes is None:
        infix_finditer = nlp.tokenizer.infix_finditer
    else:
        infix_finditer = spacy.util.compile_infix_regex(tuple(list(nlp.Defaults.infixes) + custom_infixes)).finditer

    return spacy.tokenizer.Tokenizer(nlp.vocab, 
                                     rules=nlp.tokenizer.rules,
                                     prefix_search=prefix_search, 
                                     infix_finditer=infix_finditer, 
                                     suffix_search=suffix_search,
                                     token_match=nlp.tokenizer.token_match, 
                                     url_match=nlp.tokenizer.url_match) 
