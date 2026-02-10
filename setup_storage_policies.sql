-- Supabase Storage RLS Policies for 'documents' bucket
-- Run this in your Supabase SQL Editor after creating the bucket

-- Policy 1: Users can upload their own documents
-- Files are stored in format: documents/{account_id}/{filename}
-- This policy allows authenticated users to upload files to their own folder
CREATE POLICY "Users can upload documents"
ON storage.objects
FOR INSERT
TO authenticated
WITH CHECK (
  bucket_id = 'documents' AND
  (storage.foldername(name))[1] IN (
    SELECT id::text FROM accounts WHERE user_id = auth.uid()
  )
);

-- Policy 2: Users can read their own documents
CREATE POLICY "Users can read own documents"
ON storage.objects
FOR SELECT
TO authenticated
USING (
  bucket_id = 'documents' AND
  (storage.foldername(name))[1] IN (
    SELECT id::text FROM accounts WHERE user_id = auth.uid()
  )
);

-- Policy 3: Users can update their own documents
CREATE POLICY "Users can update own documents"
ON storage.objects
FOR UPDATE
TO authenticated
USING (
  bucket_id = 'documents' AND
  (storage.foldername(name))[1] IN (
    SELECT id::text FROM accounts WHERE user_id = auth.uid()
  )
);

-- Policy 4: Users can delete their own documents
CREATE POLICY "Users can delete own documents"
ON storage.objects
FOR DELETE
TO authenticated
USING (
  bucket_id = 'documents' AND
  (storage.foldername(name))[1] IN (
    SELECT id::text FROM accounts WHERE user_id = auth.uid()
  )
);

-- Note: Service role (used by backend) automatically has full access
-- No policy needed for service_role as it bypasses RLS
