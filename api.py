import os
import re
import joblib
import torch
import spacy
from transformers import AutoModelForSequenceClassification, AutoTokenizer
import numpy as np
import pandas as pd
from flask import Flask, request, jsonify
from werkzeug.utils import secure_filename
import logging
# import concurrent.futures
import json
from email.parser import Parser as EmailParser
import datetime
import eml_parser
nlp = spacy.load('en_core_web_md')


# Set up root logger, and add a file handler to root logger
logging.basicConfig(filename = 'API_LOGS/log_file.log',
                    filemode='w',
                    level = logging.DEBUG,
                    format = '%(asctime)s:%(levelname)s:%(filename)s:%(funcName)s:%(lineno)d:%(message)s')

logger = logging.getLogger()


app = Flask(__name__)



def extract_text_eml(eml_path, encoding='utf-8', errors = 'strict'):

    '''Function to extract body of eml'''

    with open(eml_path, encoding=encoding, errors=errors) as stream:
        parser = EmailParser()
        message = parser.parse(stream)

    text_content = []
    for part in message.walk():
        if part.get_content_type().startswith('text/plain'):
            text_content.append(part.get_payload())

    text = '\n\n'.join(text_content)
    return text



ep = eml_parser.EmlParser()

def read_mail(file_path):

    file_dict = {}

    with open(file_path, 'rb') as fhd1:
        raw_email = fhd1.read()

    parsed_eml = ep.decode_email_bytes(raw_email)

    subject = parsed_eml['header']['subject']
    to_person = parsed_eml['header']['to']
    from_person = parsed_eml['header']['from']
    date = parsed_eml['header']['date']
    body = extract_text_eml(file_path, errors = 'ignore')

    file_dict['from'] = from_person
    file_dict['to'] = to_person
    file_dict['date'] = date
    file_dict['subject'] = subject
    file_dict['body'] = body

    return file_dict



def clean_text(ip_dict):

    clean_dict = {}
    for k, v in ip_dict.items():

        doc = nlp(v['body'])

        v['body'] = [i.text for i in doc]
        v['body'] = [i for i in v['body'] if i != '\n']
        v['body'] = [re.sub(r'[^a-zA-Z0-9.]', '', i) for i in v['body']]
        v['body'] = [re.sub(r'\s+', ' ', i, flags=re.I) for i in v['body']]
        v['body'] = [i for i in v['body'] if i != '']
        v['body'] = ' '.join(v['body'])
        clean_dict[k] = v

    return clean_dict



def dc_classify(ip_dictt):

    for k, v in ip_dictt.items():
        inputs = tokenizer_global(v['body'], return_tensors="pt", max_length = 512, padding = 'max_length', truncation=True).to(device)

        with torch.no_grad():
            logits = model_global(**inputs).logits

        predicted_class_id = logits.argmax().item()
        v['res'] = (model_global.config.id2label[predicted_class_id])

    return ip_dictt




@app.route('/upload', methods = ['POST', 'GET'])
def upload_file():

    if request.method == 'POST':
        if 'file' not in request.files:
            logger.debug(f'"file" keyword is missing in the request!')
            print(f'"file" keyword is missing in the request!')
            return jsonify({'ERROR' : '"file" keyword is missing in the request!'}), 400

        final_d = {}
        for uploaded_file in request.files.getlist('file'):
            if uploaded_file and uploaded_file.filename.endswith(('.eml', '.EML')) and uploaded_file.filename != '':

                logger.debug(f'Saving file...')
                uploaded_file.save(os.path.join('eml_files', uploaded_file.filename))
                logger.debug(f'File saved!')

                logger.debug(f'renaming the filename...')
                print(f'renaming the filename...')
                new_name = re.sub(r'[^a-zA-Z]', '', os.path.splitext(uploaded_file.filename)[0]) + os.path.splitext(uploaded_file.filename)[1]

                logger.debug(f'Storing the filename!')
                print(f'Storing the filename!')
                secured_filename =  secure_filename(new_name)

                final_d[uploaded_file.filename] = read_mail(os.path.join('eml_files', uploaded_file.filename))

        cleaned_dict = clean_text(final_d)
        results = dc_classify(cleaned_dict)

        df_path = 'data.joblib'
        if os.path.exists(df_path):
            df = joblib.load(df_path)
        else:
            df = pd.DataFrame()

        temp_list = [pd.DataFrame(v) for k, v in results.items()]
        temp_list.append(df)
        final_df = pd.concat(temp_list)
        joblib.dump(final_df, df_path)

        fin = {}
        for k, v in results.items():
            inner = {}
            for k1, v1 in v.items():
                inner['from'] = v['from']
                inner['res'] = v['res']
            fin[k] = inner

        return jsonify(fin), 200

    else:
        logger.debug(f'Uploaded file is not valid! Please check the extension/file')
        return jsonify({'ERROR' : 'Please upload a valid eml file!'}), 400




if __name__ == '__main__':

    device = "cuda" if torch.cuda.is_available() else "cpu"
    print(f"Using device: {device}")

    logger.debug(f'loading all models...')
    print(f'loading all the models...')
    os.makedirs('eml_files', exist_ok=True)

    tokenizer_global = AutoTokenizer.from_pretrained("models--sshreyy--eml_parse_1/snapshots/64dca9d5c9d7ca5f3e7d38d201d1d46357677fd5")#, cache_dir="./")
    model_global = AutoModelForSequenceClassification.from_pretrained("models--sshreyy--eml_parse_1/snapshots/64dca9d5c9d7ca5f3e7d38d201d1d46357677fd5").to(device)#, cache_dir="./")

    nlp = spacy.load('en_core_web_md')

    app.run(debug=True, port = 6996, host = '0.0.0.0')
