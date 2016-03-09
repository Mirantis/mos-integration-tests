#!/usr/bin/env bash

source openrc

OS_IMAGE_API_VERSION=${1:?"You should pass API version (1 or 2)"}
echo "Start test with API v${OS_IMAGE_API_VERSION}"
IMAGE_NAME=Test_$RANDOM
IMAGE_ID=$(python -c 'import uuid; print uuid.uuid4()')

export OS_IMAGE_API_VERSION

fallocate -l 120GB $IMAGE_NAME
if [[ $? -ne 0 ]]; then
    echo "Error during creation image file"
    exit 1
fi

echo "Start uploading"

glance image-create --id $IMAGE_ID --name $IMAGE_NAME --container-format bare \
    --disk-format qcow2 --file $IMAGE_NAME --progress
if [[ $? -ne 0 ]]; then
    echo "Error during creation image"
    exit 1
fi

echo "Checking image uploaded"

glance image-show $IMAGE_ID > test.log
if [[ $? -ne 0 ]]; then
    cat test.log
    echo "Uploaded image is not present in list"
    exit 1
fi

echo "Checking image status is active"

glance image-show $IMAGE_ID | grep 'status' | grep 'active' > test.log
if [[ $? -ne 0 ]]; then
    cat test.log
    echo "Image status is not 'active'"
    exit 1
fi

echo "Deleting image"

glance image-delete $IMAGE_ID
if [[ $? -ne 0 ]]; then
    echo "Error during deleting image"
    exit 1
fi

echo "Checking image deleted"

glance image-list | grep $IMAGE_ID > test.log
if [[ $? -eq 0 ]]; then
    cat test.log
    echo "Image still present in list"
    exit 1
fi

rm $IMAGE_NAME
rm test.log
echo "Test is passed"
