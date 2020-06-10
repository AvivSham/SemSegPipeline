import tensorflow as tf
import random

AUTOTUNE = tf.data.experimental.AUTOTUNE


class DataLoader(object):
    """A TensorFlow Dataset API based loader for semantic segmentation problems."""

    def __init__(self, image_paths, mask_paths, image_size, channels=[3, 3], crop_percent=None, seed=None,
                 augment=True, compose=False, one_hot_encoding=False, palette=None):
        """
        Initializes the data loader object
        Args:
            image_paths: List of paths of train images.
            mask_paths: List of paths of train masks (segmentation masks)
            image_size: Int, the final height, width of the loaded images.
            channels: List of ints, first element is number of channels in images,
                      second is the number of channels in the mask image (needed to
                      correctly read the images into tensorflow.)
            crop_percent: Float in the range 0-1, defining percentage of image 
                          to randomly crop.
            palette: A list of RGB pixel values in the mask. If specified, the mask
                     will be one hot encoded along the channel dimension.
            seed: An int, if not specified, chosen randomly. Used as the seed for 
                  the RNG in the data pipeline.
        """
        self.image_paths = image_paths
        self.mask_paths = mask_paths
        self.palette = palette
        self.image_size = image_size
        self.augment = augment
        self.compose = compose
        self.one_hot_encoding = one_hot_encoding
        if crop_percent is not None:
            if 0.0 < crop_percent <= 1.0:
                self.crop_percent = tf.constant(crop_percent, tf.float32)
            elif 0 < crop_percent <= 100:
                self.crop_percent = tf.constant(crop_percent / 100., tf.float32)
            else:
                raise ValueError("Invalid value entered for crop size. Please use an \
                                  integer between 0 and 100, or a float between 0 and 1.0")
        else:
            self.crop_percent = None
        self.channels = channels
        if seed is None:
            self.seed = random.randint(0, 1000)
        else:
            self.seed = seed

    def _corrupt_brightness(self, image, mask):
        """
        Radnomly applies a random brightness change.
        """
        cond_brightness = tf.cast(tf.random.uniform(
            [], maxval=2, dtype=tf.int32), tf.bool)
        image = tf.cond(cond_brightness, lambda: tf.image.random_brightness(
            image, 0.1), lambda: tf.identity(image))
        return image, mask


    def _corrupt_contrast(self, image, mask):
        """
        Randomly applies a random contrast change.
        """
        cond_contrast = tf.cast(tf.random.uniform(
            [], maxval=2, dtype=tf.int32), tf.bool)
        image = tf.cond(cond_contrast, lambda: tf.image.random_contrast(
            image, 0.1, 0.8), lambda: tf.identity(image))
        return image, mask


    def _corrupt_saturation(self, image, mask):
        """
        Randomly applies a random saturation change.
        """
        cond_saturation = tf.cast(tf.random.uniform(
            [], maxval=2, dtype=tf.int32), tf.bool)
        image = tf.cond(cond_saturation, lambda: tf.image.random_saturation(
            image, 0.1, 0.8), lambda: tf.identity(image))
        return image, mask


    def _crop_random(self, image, mask):
        """
        Randomly crops image and mask in accord.
        """
        cond_crop_image = tf.cast(tf.random.uniform(
            [], maxval=2, dtype=tf.int32, seed=self.seed), tf.bool)
        cond_crop_mask = tf.cast(tf.random.uniform(
            [], maxval=2, dtype=tf.int32, seed=self.seed), tf.bool)

        shape = tf.cast(tf.shape(image), tf.float32)
        h = tf.cast(shape[0] * self.crop_percent, tf.int32)
        w = tf.cast(shape[1] * self.crop_percent, tf.int32)

        image = tf.cond(cond_crop_image, lambda: tf.image.random_crop(
            image, [h, w, self.channels[0]], seed=self.seed), lambda: tf.identity(image))
        mask = tf.cond(cond_crop_mask, lambda: tf.image.random_crop(
            mask, [h, w, self.channels[1]], seed=self.seed), lambda: tf.identity(mask))

        return image, mask


    def _flip_left_right(self, image, mask):
        """
        Randomly flips image and mask left or right in accord.
        """
        image = tf.image.random_flip_left_right(image, seed=self.seed)
        mask = tf.image.random_flip_left_right(mask, seed=self.seed)

        return image, mask


    def _resize_data(self, image, mask):
        """
        Resizes images to specified size.
        """
        image = tf.image.resize(image, [self.image_size, self.image_size])
        mask = tf.image.resize(mask, [self.image_size, self.image_size], method='nearest')
        
        return image, mask


    def _parse_data(self, image_paths, mask_paths):
        """
        Reads image and mask files depending on
        specified exxtension.
        """
        image_content = tf.io.read_file(image_paths)
        mask_content = tf.io.read_file(mask_paths)

        images = tf.image.decode_jpeg(image_content, channels=self.channels[0])
        masks = tf.image.decode_jpeg(mask_content, channels=self.channels[1])

        return images, masks


    def _one_hot_encode(self, image, mask):
        """
        Converts mask to a one-hot encoding specified by the semantic map.
        """
        one_hot_map = []
        for colour in self.palette:
            class_map = tf.reduce_all(tf.equal(mask, colour), axis=-1)
            one_hot_map.append(class_map)
        one_hot_map = tf.stack(one_hot_map, axis=-1)
        one_hot_map = tf.cast(one_hot_map, tf.float32)
        
        return image, one_hot_map

    def _map_function(self, images_path, masks_path):
        image, mask = self._parse_data(images_path, masks_path)

        if self.augment:
            if self.compose:
                image, mask = self._corrupt_brightness(image, mask)
                image, mask = self._corrupt_contrast(image, mask)
                image, mask = self._corrupt_saturation(image, mask)
                image, mask = self._crop_random(image, mask)
                image, mask = self._flip_left_right(image, mask)
            else:
                options = [self._corrupt_brightness,
                           self._corrupt_contrast,
                           self._corrupt_saturation,
                           self._crop_random,
                           self._flip_left_right]
                augment_func = random.choice(options)
                image, mask = augment_func(images_path, masks_path)

        if self.one_hot_encoding:
            if self.palette is None:
                raise ValueError('No Palette for one-hot encoding specified in the data loader! \
                                  please specify one when initializing the loader.')
            image, mask = self._one_hot_encode(image, mask)

        image, mask = self._resize_data(image, mask)
        return image, mask


    def data_batch(self, batch_size, shuffle=False):
        """
        Reads data, normalizes it, shuffles it, then batches it, returns a
        the next element in dataset op and the dataset initializer op.
        Inputs:
            batch_size: Number of images/masks in each batch returned.
            augment: Boolean, whether to augment data or not.
            shuffle: Boolean, whether to shuffle data in buffer or not.
            one_hot_encode: Boolean, whether to one hot encode the mask image or not.
                            Encoding will done according to the palette specified when
                            initializing the object.
        Returns:
            data: A tf dataset object.
        """

        # Create dataset out of the 2 files:
        data = tf.data.Dataset.from_tensor_slices((self.image_paths, self.mask_paths))

        # Parse images and labels
        data = data.map(self._map_function, num_parallel_calls=AUTOTUNE)

        if shuffle:
            # Prefetch, shuffle then batch
            data = data.prefetch(AUTOTUNE).shuffle(random.randint(0, len(self.image_paths))).batch(batch_size)
        else:
            # Batch and prefetch
            data = data.batch(batch_size).prefetch(AUTOTUNE)

        return data
