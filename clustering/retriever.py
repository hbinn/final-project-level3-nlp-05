import json
import argparse
import re
import string
import timeit

import pandas as pd
import numpy as np
from collections import defaultdict
from scipy import spatial
from sklearn import cluster

from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.cluster import DBSCAN
from sklearn.preprocessing import normalize

from konlpy.tag import Hannanum #Okt
from datetime import date, timedelta


def filter_sentence_articles(df):
    """ 300자 이하 3문장 이하인 기사 제거 """
    drop_index_list = [] 
    for i in range(len(df['article'])):
        if len(df['article'][i]) < 300 or df['article'][i].count('다.') < 3:
            drop_index_list.append(i)         
    df = df.drop(drop_index_list)
    df.index = range(len(df)) 
    return df

# title, article 전처리
def preprocess(sent, exclude): # 유니코드
    """ 클러스터링을 위한 전처리 """
    total =''
    email = '([a-zA-Z0-9_.+-]+@[a-zA-Z0-9-]+\.[a-zA-Z0-9-.]+)'
    sent = re.sub(email, '', sent) # 이메일 지우기
    for chr in sent:
        if chr not in exclude or chr == '.': total += chr
    return total


def json_to_df(json_path) :
    """ 크롤링된 json 파일에서 df로 변환 """
    df = pd.read_json(json_path)
    df.drop(['id', 'category', 'publish_date', 'extractive', 'abstractive'], axis=1, inplace=True)
    result = ''
    for i in range(len(df['article'])):
        result = []
        for j in range(len(df['article'][i])):
            result += (df['article'][i][j]['sentence']).strip()
        df['article'][i] =''.join(result)
    return df

def corpus_to_sentence(article):
    """ article 문장으로 나누기 """
    splited_article = []
    sentences = article.split(". ")
    for sentence in sentences:
        if sentence:
            new_sentence = sentence + "." if sentence[-1] != "." and sentence[-1] == "다" else sentence
            splited_article.append(new_sentence)
    return splited_article

def print_clustered_data(df, result, print_titles = True):
    """ 클러스터링 후 클러스터별 기사 및 분류비율 확인 """
    for cluster_num in set(result):
        # -1,0은 노이즈 판별이 났거나 클러스터링이 안된 경우
        if(cluster_num == -1 or cluster_num == 0): 
            continue
        else:
            print("cluster num : {}".format(cluster_num))
            temp_df = df[df['cluster'] == cluster_num] # cluster num 별로 조회
            
            if print_titles:
                for title in temp_df['title']:
                    print(title) # 제목으로 살펴보자
                print()
    unlabeled_counts = len(df[df['cluster'] == -1]) + len(df[df['cluster'] == 0])
        
    print(f'분류 불가능한 기사 개수 : {unlabeled_counts}')
    print(f'분류 불가 비율 : {100*unlabeled_counts/len(df):.3f}%')


def retrieve_main_title(df, centers, dict):
    """ 클러스터별 Center과 가장 가까운(Cosine Distance 기준) 기사 추출 """
    feature_vector_idx = []
    feature_title = []
    feature_article = []
    for i in range(1,len(centers)-1):
        min_idx,min =  0,1
        temp = dict[i][0].to_dict()

        for idx, vector in temp.items():
            dist = spatial.distance.cosine(centers[i+1],vector)
            if  dist < min:
                min_idx = idx
                min = dist
        feature_vector_idx.append(min_idx)
        feature_title.append(df['title'][min_idx])
        feature_article.append(df['article'][min_idx])
    return feature_vector_idx, feature_title, feature_article


def retrieve_topk_clusters(df, topk = 3):
    """ 분류 가능 클러스터 중에서 사이즈 큰 상위 k개 클러스터 추출 """
    cluster_counts = df['cluster'].groupby(df['cluster']).count()
    sorted_clusters = sorted(zip(cluster_counts[2:].index,cluster_counts[2:]), reverse = True, key = lambda t: t[1])
    return [k for k,_ in sorted_clusters][:topk]


def get_cluster_details_dbscan(centers, feature_names, feature_title, feature_article, top_n_features=10):
    """ 분류된 클러스터에 대한 정보 dict형태로 반환 """
    cluster_details = {}
    # if cluster_range == None:
    #     cluster_range = range(1,len(centers)-3)
    # else: 
    #     cluster_range = retrieve_topk_clusters(df)
    
    #개별 군집별로 iteration하면서 핵심단어, 그 단어의 중심 위치 상대값, 대상 제목 입력
    for cluster_num in range(1,len(centers)-1): # -1, 0 제외
        # 개별 군집별 정보를 담을 데이터 초기화. 
        cluster_details[cluster_num] = {}
        cluster_details[cluster_num]['cluster'] = cluster_num
        
        # cluster_centers_.argsort()[:,::-1] 로 구한 index 를 이용하여 top n 피처 단어를 구함.
        top_k_idx = centers[cluster_num+1].argsort()[::-1][:top_n_features] 
        top_features = [feature_names[ind] for ind in top_k_idx]
        cluster_details[cluster_num]['top_features'] = top_features

        # top title, article
        cluster_details[cluster_num]['title'] = feature_title[cluster_num-1]
        cluster_details[cluster_num]['article'] = feature_article[cluster_num-1]
    return cluster_details

def print_cluster_details(cluster_details):    
    """ Cluster 정보 출력 """
    for cluster_num in cluster_details.keys():
        print(f'####### Cluster - {cluster_num}')
        print('Top features: ',cluster_details[cluster_num]['top_features'])
        print('Title :',cluster_details[cluster_num]['title'])
        print('Article :',cluster_details[cluster_num]['article'])
        print('='*50)

def retrieve_json(day, category, cluster_details, retrive_topk_clusters):
    id = ""
    if category == "경제" : id = "1-"
    elif category == "사회" : id = "2-"
    elif category == "정치": id = "3-"
    total = []
    num = 1
    for cluster_num in retrive_topk_clusters:
        dict = {}
        dict['id'] = id + str(num) +"-"+ str(day)
        dict['category'] = category
        dict['title'] = cluster_details[cluster_num]['title']
        article = cluster_details[cluster_num]['article'] # 다.으로 분리 index
        
        tmp = []
        new_list = corpus_to_sentence(article)
        for i in range(len(new_list)):
            index_text = {'index': i, 'text':new_list[i]}
            tmp.append([index_text])
        dict['title'] = tmp
        total.append(dict)
        num += 1
    with open(f'clustering_{day}_{category}.json', 'w') as f:
        json.dump(total, f, ensure_ascii=False) 


##################################################################################
if __name__ == "__main__":
    start = timeit.default_timer()
    # 사회, 경제, 정치...
    # 날짜랑 카테고리 parser
    parser = argparse.ArgumentParser()
    parser.add_argument(
        '--date', 
        default=(date.today() - timedelta(1)).strftime("%Y%m%d"),
        type=str, 
        help="date of news"
    )
    parser.add_argument(
        "--category",
        default="politics",
        type=str,
        help="category of news",
        choices=["society", "politics", "economic"]
    )
    category_list = {'society':'사회',
        'politics':'정치',
        'economic':'경제',
        'foreign':'국제',
        'culture':'문화',
        'entertain':'연예',
        'sports':'스포츠',
        'digital':'IT'}
    args = parser.parse_args()

    daily_category_specific_dir = f'../news/articles/daum_articles_{args.date}_{category_list[args.category]}.json'

    df = json_to_df(daily_category_specific_dir)
    print(f'{len(df)} articles exist for Category : {category_list[args.category]}', '\n')

    # 전처리
    exclude = string.punctuation + '‘’·“”…◆\'△☆/★■\\▲▶\"▷◎▶▲◀☎◇↑☞『』☏‥◈▷【】🎧�◈-'
    print(f'Preprocessed Characters: {exclude}', '\n')
    df['concat'] = ''
    for i in range(len(df)):
        sent = preprocess(df['title'][i], exclude)
        df['title'][i] = sent
        sent = preprocess(df['article'][i], exclude)
        df['article'][i] = sent
        # sent = preprocess(df['concat'][i], exclude)
        df['concat'][i] = df['title'][i] + ' '+ df['article'][i]
        
    
    # 3문장 300자 필터
    df = filter_sentence_articles(df)

    han = Hannanum() 
    df['concat_nouns'] = ''

    # Preprocessing nouns from concated (title + article)
    for i in range(len(df['concat'])):
        tmp = ' '.join(han.nouns(df['concat'][i]))
        df['concat_nouns'][i] = tmp
    nouns = ["".join(noun) for noun in df['concat_nouns']]

    # sent 3, string 300, nouns==0 여기서

    # TFIDF Vectorizing
    tfidf_vectorizer = TfidfVectorizer(min_df = 5, ngram_range=(1,2))#,max_features=3000)
    vector = tfidf_vectorizer.fit_transform(nouns).toarray()
    print(f'Shape of TFIDF Matrix: {vector.shape}', '\n')

    # DBSCAN
    vector = normalize(np.array(vector))
    model = DBSCAN(eps=0.5 ,min_samples=5, metric = "cosine") # Cosine Distance 
    result = model.fit_predict(vector)
    df['cluster'] = result

    # print clustered data
    print_clustered_data(df,result)

    # dict building for center caculation
    df['vector'] = vector.tolist()
    dict = defaultdict(list)
    for i in range(-1, df['cluster'].nunique()-1):
        dict[i].append(df[df['cluster'] == i]['vector'])

    # center for each cluster
    centers = [np.mean(np.array((list(dict[i][0]))), axis = 0) for i in dict.keys()]

    # fetches 
    _, feature_title, feature_article = retrieve_main_title(df, centers, dict)

    # fetches corresponding vocabs from TFIDF Vectorizer
    feature_names = tfidf_vectorizer.get_feature_names_out()
    
    cluster_details = get_cluster_details_dbscan(centers, feature_names, feature_title,feature_article,top_n_features=10)

    print('Cluster Details...')
    print(cluster_details)

    execution_time = timeit.default_timer() - start
    print(f"Program Executed in {execution_time:.2f}s", '\n') # returns seconds
    print_cluster_details(cluster_details)

    topk_list= retrieve_topk_clusters(df, 3)
    retrieve_json(args.date, category_list[args.category], cluster_details, topk_list)