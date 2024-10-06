import onnx # type: ignore
import numpy as np
import pandas as pd
import cv2

import redis
import insightface
import os

from insightface.app import FaceAnalysis
from sklearn.metrics import pairwise
from sklearn.metrics.pairwise import pairwise_distances
from sklearn.metrics.pairwise import cosine_similarity

import time
from datetime import datetime

#DB Connection

hostname = 'redis-14658.c305.ap-south-1-1.ec2.redns.redis-cloud.com'
portnumber= 14658
password = 'MTbC6fMEwN8eVuDvoVTleXABnsGyYjHL'

r = redis.StrictRedis(host = hostname,
                     port = portnumber,
                     password = password)

#Retrive Data From DB
def retrive_data(name):
    retrive_dict = r.hgetall(name)
    retrive_series = pd.Series(retrive_dict)
    retrive_series = retrive_series.apply(lambda x: np.frombuffer(x,dtype = np.float32))
    index = retrive_series.index
    index = list(map(lambda x: x.decode(),index))
    retrive_series.index = index
    retrive_df = retrive_series.to_frame().reset_index()
    retrive_df.columns = ['name_role','facial_features']
    retrive_df[['Name','Role']] = retrive_df['name_role'].apply(lambda x: x.split('@')).apply(pd.Series)
    return retrive_df[['Name','Role','facial_features']]

# Configure Face Analysis
faceapp = FaceAnalysis(name='buffalo_sc',
                    root='insightface_model',
                    providers=['CPUExecutionProvider'])

faceapp.prepare(ctx_id=0,det_size=(640,640),det_thresh=0.5)

#Ml Search Algarithom
def ml_search_algorithm(dataframe,feature_column,test_vector,name_role=['Name','Role'],thresh=0.5):
    
# step1 data frame
    dataframe = dataframe.copy()
#step 2 embedding
    X_list = dataframe[feature_column].tolist()
    # print(X_list)
    # x = np.asarray(X_list)
        # Pad the arrays to make them all the same length
    max_len = max(len(x) for x in X_list)
    padded_X_list = [np.pad(x, (0, max_len - len(x))) for x in X_list]
    
    x = np.asarray(padded_X_list)
     # Pad the test vector to match the shape of x
    test_vector = np.pad(test_vector, (0, max_len - len(test_vector)))
     # Calculate cosine similarity
    similar = cosine_similarity(x, test_vector.reshape(1, -1))
    
        # Calculate cosine similarity
    similar = 1 - pairwise_distances(x, test_vector.reshape(1, -1), metric='cosine')
    
    # Find the most similar match
    idx = np.argmax(similar)
    person_name, person_role = dataframe[name_role[0]][idx], dataframe[name_role[1]][idx]
    
    if similar[idx] < thresh:
        person_name, person_role = 'Unknown', 'Unknown'
    
    return person_name, person_role
    
# #3 cosine
#     similar = pairwise.cosine_similarity(x,test_vector.reshape(1,-1))
#     similar_arr = np.array(similar).flatten()
#     dataframe['cosine'] = similar_arr
# #4 filter data
#     data_filter = dataframe.query(f'cosine >= {thresh}')
#     if len(data_filter) > 0:
#         data_filter.reset_index(drop=True,inplace=True)
#         argmax = data_filter['cosine'].argmax()
#         person_name,person_role = data_filter.loc[argmax][name_role]

#     else:
#         person_name = 'Unknown'
#         person_role = 'Unknown'

#     return person_name , person_role


class RealTimePred:
    def __init__(self):
        self.logs = dict(name=[],role=[],current_time=[])
        

    def reset_dict(self):
        self.logs = dict(name=[],role=[],current_time=[])

    def saveLogs_db(self):
        dataframe = pd.DataFrame(self.logs)
        dataframe.drop_duplicates ('name',inplace=True)

        name_list = dataframe['name'].tolist()
        role_list = dataframe['role'].tolist()
        ctime_list = dataframe['current_time'].tolist()
        encoded_list=[]
        for name, role, ctime in zip(name_list,role_list,ctime_list):
            if name != 'Unknown':
                concat_string = f"{name}@{role}@{ctime}"
                encoded_list.append(concat_string)

        if len(encoded_list)>0:
            r.lpush('attendance:logs',*encoded_list)

        self.reset_dict()




    def face_prediction(self,test_image,dataframe,
                        feature_column,name_role=['Name','Role'],thresh=0.5):
        
        current_time = str(datetime.now())

        result = faceapp.get(test_image)
        test_copy = test_image.copy()
        
        for res in result:
            x1,y1,x2,y2 = res['bbox'].astype(int)
            embeddings = res['embedding']
            person_name , person_role = ml_search_algorithm(dataframe,feature_column,
                                                            test_vector=embeddings,
                                                            name_role=name_role,
                                                            thresh=thresh)
            if person_name == 'Unknown':
                color =(0,0,255)
            else:
                color = (0,255,0)
            # print(person_name,person_role)
            cv2.rectangle(test_copy,(x1,y1),(x2,y2),color)
            text_gen = person_name
            cv2.putText(test_copy,text_gen,(x1,y1),cv2.FONT_HERSHEY_DUPLEX,0.7,color,1)
            cv2.putText(test_copy,current_time,(x1,y2+10),cv2.FONT_HERSHEY_DUPLEX,0.7,color,1)

            self.logs['name'].append(person_name)
            self.logs['role'].append(person_role)
            self.logs['current_time'].append(current_time)
        return test_copy
    
class RegistrationForm:

    def __init__(self):
        self.sample = 0
    def reset(self):
        self.sample=0

    def get_embedding(self,frame):
        results = faceapp.get(frame,max_num=1)

        for res in results:
            self.sample +=1
            x1,y1,x2,y2 = res['bbox'].astype(int)
            cv2.rectangle(frame,(x1,y1),(x2,y2),(0,255,0),1)
            text = f"samples = {self.sample}"

            cv2.putText(frame,text,(x1,y1),cv2.FONT_HERSHEY_SIMPLEX,0.6,(255,0,255),1)
            embeddings = None
            embeddings = res['embedding']
        
        return frame,embeddings
    
    def save_data_in_db(self,name,role):
        if name is not None:
            if name.strip()!='':
                key = f'{name}@{role}'
            else:
                return 'name_false'
        else:
            return 'name_false'
        
        if 'face_embedding.txt' not in os.listdir():
            return 'file_false'

        x_array = np.loadtxt('face_embedding.txt',dtype=np.float32)

        receieved_samples = int(x_array.size/512)

        x_array = x_array.reshape(receieved_samples,512)
        x_array = np.asarray(x_array)
        x_mean = x_array.mean(axis=1)
        x_mean_bytes = x_mean.tobytes()

        r.hset(name='academy:register',key=key,value=x_mean_bytes)

        os.remove('face_embedding.txt')
        self.reset()

        return True